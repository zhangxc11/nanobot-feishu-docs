#!/usr/bin/env python3
"""飞书文档操作 CLI — nanobot feishu-docs skill

统一入口脚本，提供飞书文档的创建、读取、写入功能。
从 ~/.nanobot/config.json 自动加载飞书应用凭证（ST 应用）。

用法:
  python3 feishu_doc.py create --title "标题" [--folder TOKEN]
  python3 feishu_doc.py write --doc DOC_ID --markdown "内容" [--markdown-file FILE]
  python3 feishu_doc.py read --doc DOC_ID [--format raw|blocks]
  python3 feishu_doc.py create-and-write --title "标题" --markdown "内容" [--markdown-file FILE] [--folder TOKEN]

安全说明:
  - appSecret 仅在此脚本进程内使用，不输出到 stdout
  - Agent 不直接接触密钥
"""

import argparse
import json
import os
import sys
from typing import Optional, Tuple

# Add current dir to path for md_to_blocks import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from md_to_blocks import markdown_to_blocks

try:
    import lark_oapi as lark
    from lark_oapi.api.docx.v1 import *
except ImportError:
    print("ERROR: lark-oapi not installed. Run: pip install lark-oapi", file=sys.stderr)
    sys.exit(1)


# ── Config loading ────────────────────────────────────────────────────

def load_feishu_credentials(app_name: str = "ST") -> Tuple[str, str]:
    """Load Feishu app credentials from nanobot config.

    Args:
        app_name: Name of the Feishu app in config (default: "ST")

    Returns:
        Tuple of (app_id, app_secret)

    Raises:
        SystemExit: If config not found or app not configured
    """
    config_path = os.path.expanduser("~/.nanobot/config.json")
    if not os.path.exists(config_path):
        print(f"ERROR: Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, 'r') as f:
        config = json.load(f)

    feishu_apps = config.get("channels", {}).get("feishu", [])
    if not isinstance(feishu_apps, list):
        print("ERROR: channels.feishu should be an array in config.json", file=sys.stderr)
        sys.exit(1)

    target_app = None
    for app in feishu_apps:
        if app.get("name") == app_name:
            target_app = app
            break

    if not target_app:
        available = [a.get("name", "?") for a in feishu_apps]
        print(f"ERROR: Feishu app '{app_name}' not found. Available: {available}", file=sys.stderr)
        sys.exit(1)

    app_id = target_app.get("appId", "")
    app_secret = target_app.get("appSecret", "")
    if not app_id or not app_secret:
        print(f"ERROR: appId or appSecret not configured for '{app_name}'", file=sys.stderr)
        sys.exit(1)

    return app_id, app_secret


def create_client(app_name: str = "ST") -> lark.Client:
    """Create a Feishu API client.

    Args:
        app_name: Name of the Feishu app

    Returns:
        lark.Client instance
    """
    app_id, app_secret = load_feishu_credentials(app_name)
    client = lark.Client.builder() \
        .app_id(app_id) \
        .app_secret(app_secret) \
        .log_level(lark.LogLevel.WARNING) \
        .build()
    return client


# ── Document operations ───────────────────────────────────────────────

def cmd_create(args):
    """Create a new Feishu document."""
    client = create_client(args.app)

    # Build request
    body_builder = CreateDocumentRequestBody.builder() \
        .title(args.title)

    if args.folder:
        body_builder = body_builder.folder_token(args.folder)

    request = CreateDocumentRequest.builder() \
        .request_body(body_builder.build()) \
        .build()

    # Call API
    response = client.docx.v1.document.create(request)

    if not response.success():
        print(json.dumps({
            "success": False,
            "error": f"[{response.code}] {response.msg}"
        }, ensure_ascii=False))
        return 1

    doc = response.data.document
    result = {
        "success": True,
        "document_id": doc.document_id,
        "revision_id": doc.revision_id,
        "title": doc.title,
        "url": f"https://feishu.cn/docx/{doc.document_id}"
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_write(args):
    """Write content to an existing Feishu document."""
    client = create_client(args.app)

    # Get markdown content
    markdown = _get_markdown_content(args)
    if markdown is None:
        return 1

    # Convert markdown to blocks
    block_dicts = markdown_to_blocks(markdown)
    if not block_dicts:
        print(json.dumps({"success": False, "error": "No content to write"}), ensure_ascii=False)
        return 1

    # Build Block objects from dicts
    children = []
    for bd in block_dicts:
        block = Block()
        block.block_type = bd["block_type"]

        # Find the content field (text, heading1, bullet, etc.)
        for field_name in ["text", "heading1", "heading2", "heading3", "heading4",
                           "heading5", "heading6", "heading7", "heading8", "heading9",
                           "bullet", "ordered", "code", "quote", "todo", "divider"]:
            if field_name in bd:
                setattr(block, field_name, _dict_to_text(bd[field_name], field_name))
                break

        children.append(block)

    # Write blocks in batches (API limit: max 50 blocks per request)
    BATCH_SIZE = 50
    total_written = 0

    for batch_start in range(0, len(children), BATCH_SIZE):
        batch = children[batch_start:batch_start + BATCH_SIZE]

        request = CreateDocumentBlockChildrenRequest.builder() \
            .document_id(args.doc) \
            .block_id(args.doc) \
            .request_body(
                CreateDocumentBlockChildrenRequestBody.builder()
                .children(batch)
                .index(-1)
                .build()
            ) \
            .build()

        response = client.docx.v1.document_block_children.create(request)

        if not response.success():
            print(json.dumps({
                "success": False,
                "error": f"[{response.code}] {response.msg}",
                "blocks_written": total_written
            }, ensure_ascii=False))
            return 1

        total_written += len(batch)

    result = {
        "success": True,
        "document_id": args.doc,
        "blocks_written": total_written,
        "url": f"https://feishu.cn/docx/{args.doc}"
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_read(args):
    """Read content from a Feishu document."""
    client = create_client(args.app)

    if args.format == "raw":
        return _read_raw(client, args.doc)
    else:
        return _read_blocks(client, args.doc)


def _read_raw(client, doc_id: str) -> int:
    """Read document as raw text."""
    request = RawContentDocumentRequest.builder() \
        .document_id(doc_id) \
        .build()

    response = client.docx.v1.document.raw_content(request)

    if not response.success():
        print(json.dumps({
            "success": False,
            "error": f"[{response.code}] {response.msg}"
        }, ensure_ascii=False))
        return 1

    result = {
        "success": True,
        "document_id": doc_id,
        "content": response.data.content
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _read_blocks(client, doc_id: str) -> int:
    """Read document as block structure."""
    request = ListDocumentBlockRequest.builder() \
        .document_id(doc_id) \
        .page_size(500) \
        .build()

    response = client.docx.v1.document_block.list(request)

    if not response.success():
        print(json.dumps({
            "success": False,
            "error": f"[{response.code}] {response.msg}"
        }, ensure_ascii=False))
        return 1

    # Serialize blocks to JSON-friendly format
    blocks_data = []
    if response.data and response.data.items:
        for block in response.data.items:
            blocks_data.append(_block_to_dict(block))

    result = {
        "success": True,
        "document_id": doc_id,
        "block_count": len(blocks_data),
        "blocks": blocks_data
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_create_and_write(args):
    """Create a new document and write content to it."""
    client = create_client(args.app)

    # Get markdown content
    markdown = _get_markdown_content(args)
    if markdown is None:
        return 1

    # Step 1: Create document
    body_builder = CreateDocumentRequestBody.builder() \
        .title(args.title)

    if args.folder:
        body_builder = body_builder.folder_token(args.folder)

    create_request = CreateDocumentRequest.builder() \
        .request_body(body_builder.build()) \
        .build()

    create_response = client.docx.v1.document.create(create_request)

    if not create_response.success():
        print(json.dumps({
            "success": False,
            "error": f"Create failed: [{create_response.code}] {create_response.msg}"
        }, ensure_ascii=False))
        return 1

    doc_id = create_response.data.document.document_id

    # Step 2: Convert and write content
    block_dicts = markdown_to_blocks(markdown)
    if not block_dicts:
        # Document created but no content to write
        result = {
            "success": True,
            "document_id": doc_id,
            "title": args.title,
            "blocks_written": 0,
            "url": f"https://feishu.cn/docx/{doc_id}",
            "note": "Document created but no content blocks generated"
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # Build Block objects
    children = []
    for bd in block_dicts:
        block = Block()
        block.block_type = bd["block_type"]

        for field_name in ["text", "heading1", "heading2", "heading3", "heading4",
                           "heading5", "heading6", "heading7", "heading8", "heading9",
                           "bullet", "ordered", "code", "quote", "todo", "divider"]:
            if field_name in bd:
                setattr(block, field_name, _dict_to_text(bd[field_name], field_name))
                break

        children.append(block)

    # Write in batches
    BATCH_SIZE = 50
    total_written = 0

    for batch_start in range(0, len(children), BATCH_SIZE):
        batch = children[batch_start:batch_start + BATCH_SIZE]

        write_request = CreateDocumentBlockChildrenRequest.builder() \
            .document_id(doc_id) \
            .block_id(doc_id) \
            .request_body(
                CreateDocumentBlockChildrenRequestBody.builder()
                .children(batch)
                .index(-1)
                .build()
            ) \
            .build()

        write_response = client.docx.v1.document_block_children.create(write_request)

        if not write_response.success():
            print(json.dumps({
                "success": False,
                "error": f"Write failed: [{write_response.code}] {write_response.msg}",
                "document_id": doc_id,
                "blocks_written": total_written,
                "url": f"https://feishu.cn/docx/{doc_id}",
                "note": "Document was created but content write partially failed"
            }, ensure_ascii=False))
            return 1

        total_written += len(batch)

    result = {
        "success": True,
        "document_id": doc_id,
        "title": args.title,
        "blocks_written": total_written,
        "url": f"https://feishu.cn/docx/{doc_id}"
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# ── Helper functions ──────────────────────────────────────────────────

def _get_markdown_content(args) -> Optional[str]:
    """Get markdown content from args (--markdown or --markdown-file)."""
    if hasattr(args, 'markdown_file') and args.markdown_file:
        if not os.path.exists(args.markdown_file):
            print(json.dumps({
                "success": False,
                "error": f"File not found: {args.markdown_file}"
            }, ensure_ascii=False))
            return None
        with open(args.markdown_file, 'r') as f:
            return f.read()
    elif hasattr(args, 'markdown') and args.markdown:
        return args.markdown
    else:
        # Try reading from stdin if no markdown args
        if not sys.stdin.isatty():
            return sys.stdin.read()
        print(json.dumps({
            "success": False,
            "error": "No content provided. Use --markdown, --markdown-file, or pipe via stdin"
        }, ensure_ascii=False))
        return None


def _dict_to_text(d: dict, field_name: str):
    """Convert a block content dict to the appropriate lark-oapi model.

    For most block types, this is a Text object with elements.
    For divider, it's a Divider object (empty).
    """
    if field_name == "divider":
        return Divider()

    text = Text()

    if "elements" in d:
        elements = []
        for elem_dict in d["elements"]:
            te = TextElement()
            if "text_run" in elem_dict:
                tr = TextRun()
                tr.content = elem_dict["text_run"]["content"]
                style_dict = elem_dict["text_run"].get("text_element_style", {})
                if style_dict:
                    style = TextElementStyle()
                    if style_dict.get("bold"):
                        style.bold = True
                    if style_dict.get("italic"):
                        style.italic = True
                    if style_dict.get("strikethrough"):
                        style.strikethrough = True
                    if style_dict.get("inline_code"):
                        style.inline_code = True
                    if "link" in style_dict:
                        link = Link()
                        link.url = style_dict["link"]["url"]
                        style.link = link
                    tr.text_element_style = style
                else:
                    tr.text_element_style = TextElementStyle()
                te.text_run = tr
            elements.append(te)
        text.elements = elements

    if "style" in d:
        style = TextStyle()
        if "language" in d["style"]:
            style.language = d["style"]["language"]
        if "done" in d["style"]:
            style.done = d["style"]["done"]
        text.style = style

    return text


def _block_to_dict(block) -> dict:
    """Convert a lark-oapi Block object to a JSON-serializable dict."""
    result = {
        "block_id": block.block_id,
        "block_type": block.block_type,
        "parent_id": block.parent_id,
    }

    if block.children:
        result["children"] = block.children

    # Extract text content from the appropriate field
    field_map = {
        2: "text", 3: "heading1", 4: "heading2", 5: "heading3",
        6: "heading4", 7: "heading5", 8: "heading6", 9: "heading7",
        10: "heading8", 11: "heading9", 12: "bullet", 13: "ordered",
        14: "code", 15: "quote", 17: "todo",
    }

    field_name = field_map.get(block.block_type)
    if field_name:
        text_obj = getattr(block, field_name, None)
        if text_obj and hasattr(text_obj, 'elements') and text_obj.elements:
            content_parts = []
            for elem in text_obj.elements:
                if hasattr(elem, 'text_run') and elem.text_run:
                    content_parts.append(elem.text_run.content or "")
            result["content"] = "".join(content_parts)

    return result


# ── CLI argument parsing ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="飞书文档操作 CLI — nanobot feishu-docs skill",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--app", default="ST", help="Feishu app name in config (default: ST)")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # create
    create_parser = subparsers.add_parser("create", help="Create a new document")
    create_parser.add_argument("--title", required=True, help="Document title")
    create_parser.add_argument("--folder", help="Target folder token")

    # write
    write_parser = subparsers.add_parser("write", help="Write content to a document")
    write_parser.add_argument("--doc", required=True, help="Document ID")
    write_parser.add_argument("--markdown", help="Markdown content string")
    write_parser.add_argument("--markdown-file", help="Path to Markdown file")

    # read
    read_parser = subparsers.add_parser("read", help="Read document content")
    read_parser.add_argument("--doc", required=True, help="Document ID")
    read_parser.add_argument("--format", choices=["raw", "blocks"], default="raw",
                             help="Output format (default: raw)")

    # create-and-write
    caw_parser = subparsers.add_parser("create-and-write",
                                        help="Create a document and write content")
    caw_parser.add_argument("--title", required=True, help="Document title")
    caw_parser.add_argument("--folder", help="Target folder token")
    caw_parser.add_argument("--markdown", help="Markdown content string")
    caw_parser.add_argument("--markdown-file", help="Path to Markdown file")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch to command handler
    commands = {
        "create": cmd_create,
        "write": cmd_write,
        "read": cmd_read,
        "create-and-write": cmd_create_and_write,
    }

    handler = commands.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
