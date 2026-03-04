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
import time
from typing import Optional, Tuple

# Add current dir to path for md_to_blocks import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from md_to_blocks import markdown_to_blocks, BLOCK_TYPE_TABLE, BLOCK_TYPE_TEXT

try:
    import lark_oapi as lark
    from lark_oapi.api.docx.v1 import *
    from lark_oapi.api.drive.v1 import (
        ListFileCommentRequest, PatchFileCommentRequest,
        CreateFileCommentRequest, CreatePermissionMemberRequest,
        FileComment as DriveFileComment, BaseMember,
        ReplyContent, ReplyElement, TextRun as DriveTextRun,
        FileCommentReply, ReplyList,
    )
except ImportError:
    print("ERROR: lark-oapi not installed. Run: pip install lark-oapi", file=sys.stderr)
    sys.exit(1)

# For reply-comment we need requests (SDK lacks CreateFileCommentReply)
try:
    import requests as http_requests
except ImportError:
    http_requests = None


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

    # If overwrite mode, clear existing content first
    if hasattr(args, 'mode') and args.mode == 'overwrite':
        clear_result = _clear_document(client, args.doc)
        if clear_result != 0:
            return clear_result

    # Convert markdown to blocks
    block_dicts = markdown_to_blocks(markdown)
    if not block_dicts:
        print(json.dumps({"success": False, "error": "No content to write"}), ensure_ascii=False)
        return 1

    # Separate table blocks from regular blocks (tables need special handling)
    return _write_blocks_to_doc(client, args.doc, block_dicts)


def _clear_document(client, doc_id: str) -> int:
    """Clear all child blocks from a document (for overwrite mode).

    Returns 0 on success, 1 on failure.
    """
    # First, get the document's child blocks to know how many to delete
    request = ListDocumentBlockRequest.builder() \
        .document_id(doc_id) \
        .page_size(500) \
        .build()

    response = client.docx.v1.document_block.list(request)

    if not response.success():
        print(json.dumps({
            "success": False,
            "error": f"Failed to list blocks for clear: [{response.code}] {response.msg}"
        }, ensure_ascii=False))
        return 1

    if not response.data or not response.data.items:
        return 0  # Document already empty

    # Find the page block (block_type=1) — its children are the top-level blocks
    page_block = None
    for block in response.data.items:
        if block.block_type == 1:
            page_block = block
            break

    if not page_block or not page_block.children:
        return 0  # No children to delete

    child_count = len(page_block.children)
    if child_count == 0:
        return 0

    # Delete all children in batches (API may have limits)
    # BatchDelete uses start_index and end_index (exclusive)
    BATCH_SIZE = 50
    # Delete from the end to avoid index shifting issues
    remaining = child_count
    while remaining > 0:
        delete_count = min(BATCH_SIZE, remaining)
        del_request = BatchDeleteDocumentBlockChildrenRequest.builder() \
            .document_id(doc_id) \
            .block_id(doc_id) \
            .request_body(
                BatchDeleteDocumentBlockChildrenRequestBody.builder()
                .start_index(0)
                .end_index(delete_count)
                .build()
            ) \
            .build()

        del_response = client.docx.v1.document_block_children.batch_delete(del_request)

        if not del_response.success():
            print(json.dumps({
                "success": False,
                "error": f"Failed to clear document: [{del_response.code}] {del_response.msg}"
            }, ensure_ascii=False))
            return 1

        remaining -= delete_count

    return 0


def _write_blocks_to_doc(client, doc_id: str, block_dicts: list) -> int:
    """Write block dicts to a document, handling both regular blocks and tables.

    Tables need special two-step creation:
    1. Create empty table block with row_size/column_size
    2. Fill each cell with content via descendant API

    Returns exit code (0=success, 1=failure).
    """
    # Split block_dicts into segments: consecutive regular blocks vs table blocks
    segments = []
    current_regular = []

    for bd in block_dicts:
        if bd.get("block_type") == BLOCK_TYPE_TABLE:
            if current_regular:
                segments.append(("regular", current_regular))
                current_regular = []
            segments.append(("table", bd))
        else:
            current_regular.append(bd)

    if current_regular:
        segments.append(("regular", current_regular))

    total_written = 0

    for seg_type, seg_data in segments:
        if seg_type == "regular":
            count = _write_regular_blocks(client, doc_id, seg_data)
            if count < 0:
                return 1
            total_written += count
        elif seg_type == "table":
            ok = _write_table_block(client, doc_id, seg_data)
            if not ok:
                return 1
            total_written += 1

    result = {
        "success": True,
        "document_id": doc_id,
        "blocks_written": total_written,
        "url": f"https://feishu.cn/docx/{doc_id}"
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _write_regular_blocks(client, doc_id: str, block_dicts: list) -> int:
    """Write regular (non-table) blocks to document. Returns count written or -1 on error."""
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

    BATCH_SIZE = 50
    total_written = 0

    for batch_start in range(0, len(children), BATCH_SIZE):
        batch = children[batch_start:batch_start + BATCH_SIZE]

        request = CreateDocumentBlockChildrenRequest.builder() \
            .document_id(doc_id) \
            .block_id(doc_id) \
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
            return -1

        total_written += len(batch)

    return total_written


def _write_table_block(client, doc_id: str, table_dict: dict, index: int = -1) -> bool:
    """Create a table block in the document and fill cells with content.

    Feishu table creation is a two-step process:
    1. Create an empty table block (specifying row_size, column_size) via SDK
    2. The API returns the table block with pre-created cell block IDs
    3. Write content to each cell using HTTP API (SDK has JSON parse issues with cell writes)

    Args:
        client: Feishu API client
        doc_id: Document ID
        table_dict: Table block dict from markdown_to_blocks
        index: Insert position (-1 = append to end)

    Returns True on success, False on failure.
    """
    table_data = table_dict.get("table", {})
    rows = table_data.get("rows", [])
    row_count = len(rows)
    col_count = table_data.get("column_size", 0)

    if row_count == 0 or col_count == 0:
        return True  # Skip empty tables

    # Step 1: Create empty table block via SDK
    table_block = Block()
    table_block.block_type = BLOCK_TYPE_TABLE

    table_prop = TableProperty()
    table_prop.row_size = row_count
    table_prop.column_size = col_count

    table_obj = Table()
    table_obj.property = table_prop

    table_block.table = table_obj

    request = CreateDocumentBlockChildrenRequest.builder() \
        .document_id(doc_id) \
        .block_id(doc_id) \
        .request_body(
            CreateDocumentBlockChildrenRequestBody.builder()
            .children([table_block])
            .index(index)
            .build()
        ) \
        .build()

    response = client.docx.v1.document_block_children.create(request)

    if not response.success():
        print(json.dumps({
            "success": False,
            "error": f"Table create failed: [{response.code}] {response.msg}"
        }, ensure_ascii=False), file=sys.stderr)
        return False

    # Step 2: Get cell block IDs from response
    created_blocks = response.data.children if response.data else []
    if not created_blocks:
        print("Warning: Table created but no block data returned", file=sys.stderr)
        return True

    table_resp_block = None
    for cb in created_blocks:
        if cb.block_type == BLOCK_TYPE_TABLE:
            table_resp_block = cb
            break

    if not table_resp_block or not table_resp_block.table:
        print("Warning: Table block not found in response", file=sys.stderr)
        return True

    cell_ids = table_resp_block.table.cells or []

    if len(cell_ids) != row_count * col_count:
        print(f"Warning: Expected {row_count * col_count} cells, got {len(cell_ids)}", file=sys.stderr)

    # Step 3: Write content to each cell via HTTP API
    # (SDK has JSON parsing issues with cell block children create response)
    token = _get_tenant_token()
    failed_cells = []

    for row_idx, row in enumerate(rows):
        for col_idx, cell_content in enumerate(row):
            cell_flat_idx = row_idx * col_count + col_idx
            if cell_flat_idx >= len(cell_ids):
                break

            cell_block_id = cell_ids[cell_flat_idx]

            if not cell_content.strip():
                continue  # Skip empty cells

            # Build text elements with inline formatting
            elements = _parse_inline_simple_import(cell_content.strip())
            api_elements = []
            for elem_dict in elements:
                if "text_run" in elem_dict:
                    style = elem_dict["text_run"].get("text_element_style", {})
                    # Only include non-empty style fields for API compatibility
                    clean_style = {}
                    for k, v in style.items():
                        if v:  # Skip False, None, empty values
                            clean_style[k] = v
                    api_elements.append({
                        "text_run": {
                            "content": elem_dict["text_run"]["content"],
                            "text_element_style": clean_style
                        }
                    })

            url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{cell_block_id}/children"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            body = {
                "children": [{
                    "block_type": 2,
                    "text": {
                        "elements": api_elements
                    }
                }],
                "index": 0
            }

            # Retry with exponential backoff for rate limiting (HTTP 429)
            max_retries = 5
            success = False
            for attempt in range(max_retries):
                try:
                    resp = http_requests.post(url, headers=headers, json=body)
                    if resp.status_code == 200 and resp.text:
                        data = resp.json()
                        if data.get("code") == 0:
                            success = True
                            break
                        elif data.get("code") == 99991400:
                            # Rate limited by API (code-level throttle)
                            wait = 0.5 * (2 ** attempt)
                            print(f"Rate limited on cell [{row_idx},{col_idx}], "
                                  f"retry {attempt+1}/{max_retries} after {wait:.1f}s",
                                  file=sys.stderr)
                            time.sleep(wait)
                        else:
                            print(f"Warning: Failed to write cell [{row_idx},{col_idx}]: "
                                  f"[{data.get('code')}] {data.get('msg')}", file=sys.stderr)
                            break  # Non-retryable error
                    elif resp.status_code == 429:
                        wait = 0.5 * (2 ** attempt)
                        print(f"HTTP 429 on cell [{row_idx},{col_idx}], "
                              f"retry {attempt+1}/{max_retries} after {wait:.1f}s",
                              file=sys.stderr)
                        time.sleep(wait)
                    else:
                        print(f"Warning: HTTP {resp.status_code} writing cell [{row_idx},{col_idx}]",
                              file=sys.stderr)
                        break  # Non-retryable error
                except Exception as e:
                    print(f"Warning: Exception writing cell [{row_idx},{col_idx}]: {e}",
                          file=sys.stderr)
                    break

            if success:
                # Delete the default empty text block that Feishu auto-creates in each cell.
                # We inserted our content at index 0, so the empty block is now at index 1.
                del_url = (f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}"
                           f"/blocks/{cell_block_id}/children/batch_delete")
                del_body = {"start_index": 1, "end_index": 2}
                for attempt in range(max_retries):
                    try:
                        del_resp = http_requests.delete(del_url, headers=headers, json=del_body)
                        if del_resp.status_code == 200:
                            del_data = del_resp.json()
                            if del_data.get("code") == 0:
                                break
                            elif del_data.get("code") == 99991400:
                                time.sleep(0.5 * (2 ** attempt))
                            else:
                                break  # Non-retryable
                        elif del_resp.status_code == 429:
                            time.sleep(0.5 * (2 ** attempt))
                        else:
                            break
                    except Exception:
                        break
            else:
                failed_cells.append(f"[{row_idx},{col_idx}]")

    if failed_cells:
        print(f"Warning: {len(failed_cells)} cells failed to write: {', '.join(failed_cells)}",
              file=sys.stderr)

    # Step 4: Set column widths if available
    column_widths = table_data.get("column_widths", [])
    if column_widths and table_resp_block:
        table_block_id = table_resp_block.block_id
        _set_table_column_widths(doc_id, table_block_id, column_widths, token)

    return True


def _set_table_column_widths(doc_id: str, table_block_id: str,
                              column_widths: list, token: str) -> None:
    """Set column widths for a table block via PATCH API.

    Feishu's update_table_property API updates one column at a time:
    - column_index: which column to update (0-based)
    - column_width: width in px

    Args:
        doc_id: Document ID
        table_block_id: Table block ID
        column_widths: List of column widths (integers)
        token: Tenant access token
    """
    url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{table_block_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    for col_idx, width in enumerate(column_widths):
        body = {
            "update_table_property": {
                "column_width": width,
                "column_index": col_idx,
            }
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = http_requests.patch(url, headers=headers, json=body)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0:
                        break
                    elif data.get("code") == 99991400:
                        # Rate limited
                        time.sleep(0.5 * (2 ** attempt))
                    else:
                        print(f"Warning: Failed to set column {col_idx} width: "
                              f"[{data.get('code')}] {data.get('msg')}", file=sys.stderr)
                        break
                elif resp.status_code == 429:
                    time.sleep(0.5 * (2 ** attempt))
                else:
                    print(f"Warning: HTTP {resp.status_code} setting column {col_idx} width",
                          file=sys.stderr)
                    break
            except Exception as e:
                print(f"Warning: Exception setting column {col_idx} width: {e}",
                      file=sys.stderr)
                break


def _parse_inline_simple_import(text: str):
    """Import and call _parse_inline_simple from md_to_blocks."""
    from md_to_blocks import _parse_inline_simple
    return _parse_inline_simple(text)


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

    # Step 2: Convert and write content (reuse shared write logic)
    block_dicts = markdown_to_blocks(markdown)
    if not block_dicts:
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

    return _write_blocks_to_doc(client, doc_id, block_dicts)


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


# ── Comment operations ────────────────────────────────────────────────

def _get_tenant_token(app_name: str = "ST") -> str:
    """Get tenant_access_token via HTTP for APIs not covered by SDK."""
    app_id, app_secret = load_feishu_credentials(app_name)
    if http_requests is None:
        print("ERROR: 'requests' library not available", file=sys.stderr)
        sys.exit(1)
    resp = http_requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
    )
    data = resp.json()
    if data.get("code") != 0:
        print(f"ERROR: Failed to get token: {data}", file=sys.stderr)
        sys.exit(1)
    return data["tenant_access_token"]


def cmd_list_comments(args):
    """List comments on a Feishu document."""
    client = create_client(args.app)

    request = ListFileCommentRequest.builder() \
        .file_token(args.doc) \
        .file_type("docx") \
        .build()

    response = client.drive.v1.file_comment.list(request)

    if not response.success():
        print(json.dumps({
            "success": False,
            "error": f"[{response.code}] {response.msg}"
        }, ensure_ascii=False))
        return 1

    comments = []
    if response.data and response.data.items:
        for item in response.data.items:
            comment = {
                "comment_id": item.comment_id,
                "is_solved": item.is_solved,
                "quote": item.quote or "",
                "replies": [],
            }
            if item.reply_list and item.reply_list.replies:
                for reply in item.reply_list.replies:
                    reply_text = ""
                    if reply.content and reply.content.elements:
                        parts = []
                        for elem in reply.content.elements:
                            if elem.type == "text_run" and elem.text_run:
                                parts.append(elem.text_run.text or "")
                        reply_text = "".join(parts)
                    comment["replies"].append({
                        "reply_id": reply.reply_id,
                        "text": reply_text,
                    })
            # Apply status filter
            if args.status == "solved" and not item.is_solved:
                continue
            if args.status == "unsolved" and item.is_solved:
                continue
            comments.append(comment)

    result = {
        "success": True,
        "document_id": args.doc,
        "comment_count": len(comments),
        "comments": comments,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_reply_comment(args):
    """Reply to a comment on a Feishu document.

    Uses HTTP API directly because lark-oapi SDK lacks CreateFileCommentReply.
    """
    token = _get_tenant_token(args.app)

    url = (
        f"https://open.feishu.cn/open-apis/drive/v1/files/{args.doc}"
        f"/comments/{args.comment}/replies"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "content": {
            "elements": [{
                "type": "text_run",
                "text_run": {"text": args.text},
            }]
        }
    }
    resp = http_requests.post(url, headers=headers, json=body, params={"file_type": "docx"})
    data = resp.json()

    if data.get("code") == 0:
        reply_data = data.get("data", {})
        result = {
            "success": True,
            "document_id": args.doc,
            "comment_id": args.comment,
            "reply_id": reply_data.get("reply_id"),
            "text": args.text,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    else:
        print(json.dumps({
            "success": False,
            "error": f"[{data.get('code')}] {data.get('msg')}",
        }, ensure_ascii=False))
        return 1


def cmd_resolve_comment(args):
    """Mark a comment as resolved."""
    client = create_client(args.app)

    request = PatchFileCommentRequest.builder() \
        .file_token(args.doc) \
        .comment_id(args.comment) \
        .file_type("docx") \
        .request_body(DriveFileComment.builder().is_solved(True).build()) \
        .build()

    response = client.drive.v1.file_comment.patch(request)

    if response.success():
        print(json.dumps({
            "success": True,
            "document_id": args.doc,
            "comment_id": args.comment,
            "action": "resolved",
        }, ensure_ascii=False, indent=2))
        return 0
    else:
        print(json.dumps({
            "success": False,
            "error": f"[{response.code}] {response.msg}",
        }, ensure_ascii=False))
        return 1


def cmd_add_comment(args):
    """Add a new comment to a Feishu document.

    Uses HTTP API directly for reliable quote + content handling.
    """
    token = _get_tenant_token(args.app)

    url = f"https://open.feishu.cn/open-apis/drive/v1/files/{args.doc}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "reply_list": {
            "replies": [{
                "content": {
                    "elements": [{
                        "type": "text_run",
                        "text_run": {"text": args.text},
                    }]
                }
            }]
        },
    }
    if args.quote:
        body["quote"] = args.quote
    if args.is_whole:
        body["is_whole"] = True

    resp = http_requests.post(url, headers=headers, json=body, params={"file_type": "docx"})
    data = resp.json()

    if data.get("code") == 0:
        comment_data = data.get("data", {})
        result = {
            "success": True,
            "document_id": args.doc,
            "comment_id": comment_data.get("comment_id"),
            "quote": args.quote or "(whole document)",
            "text": args.text,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    else:
        print(json.dumps({
            "success": False,
            "error": f"[{data.get('code')}] {data.get('msg')}",
        }, ensure_ascii=False))
        return 1


def cmd_add_member(args):
    """Add a collaborator to a Feishu document."""
    client = create_client(args.app)

    request = CreatePermissionMemberRequest.builder() \
        .token(args.doc) \
        .type("docx") \
        .request_body(BaseMember.builder()
            .member_type("openid")
            .member_id(args.open_id)
            .perm(args.perm)
            .build()) \
        .build()

    response = client.drive.v1.permission_member.create(request)

    if response.success():
        print(json.dumps({
            "success": True,
            "document_id": args.doc,
            "open_id": args.open_id,
            "perm": args.perm,
            "action": "member_added",
        }, ensure_ascii=False, indent=2))
        return 0
    else:
        print(json.dumps({
            "success": False,
            "error": f"[{response.code}] {response.msg}",
        }, ensure_ascii=False))
        return 1


# ── Block-level editing operations ────────────────────────────────────

def cmd_patch_block(args):
    """Update the text content of a specific block in-place.

    This is the preferred way to edit documents — it preserves edit history
    and only modifies the targeted block.
    """
    token = _get_tenant_token(args.app)

    # Build text elements from markdown content
    elements = _parse_inline_simple_import(args.text)
    api_elements = []
    for elem_dict in elements:
        if "text_run" in elem_dict:
            style = elem_dict["text_run"].get("text_element_style", {})
            clean_style = {}
            for k, v in style.items():
                if v:
                    clean_style[k] = v
            api_elements.append({
                "text_run": {
                    "content": elem_dict["text_run"]["content"],
                    "text_element_style": clean_style
                }
            })

    url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{args.doc}/blocks/{args.block}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "update_text_elements": {
            "elements": api_elements
        }
    }

    try:
        resp = http_requests.patch(url, headers=headers, json=body)
        data = resp.json()
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"HTTP request failed: {e}"
        }, ensure_ascii=False))
        return 1

    if data.get("code") == 0:
        block_data = data.get("data", {}).get("block", {})
        result = {
            "success": True,
            "document_id": args.doc,
            "block_id": args.block,
            "action": "patched",
            "revision_id": data.get("data", {}).get("document_revision_id"),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    else:
        print(json.dumps({
            "success": False,
            "error": f"[{data.get('code')}] {data.get('msg')}"
        }, ensure_ascii=False))
        return 1


def cmd_delete_blocks(args):
    """Delete a range of child blocks from a document.

    Uses start_index and end_index (exclusive) relative to the parent block's children.
    Typically the parent is the page block (doc_id itself).
    """
    client = create_client(args.app)

    parent_id = args.parent or args.doc  # Default parent is the page block

    del_request = BatchDeleteDocumentBlockChildrenRequest.builder() \
        .document_id(args.doc) \
        .block_id(parent_id) \
        .request_body(
            BatchDeleteDocumentBlockChildrenRequestBody.builder()
            .start_index(args.start)
            .end_index(args.end)
            .build()
        ) \
        .build()

    del_response = client.docx.v1.document_block_children.batch_delete(del_request)

    if del_response.success():
        result = {
            "success": True,
            "document_id": args.doc,
            "parent_id": parent_id,
            "deleted_range": f"[{args.start}, {args.end})",
            "action": "deleted",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    else:
        print(json.dumps({
            "success": False,
            "error": f"[{del_response.code}] {del_response.msg}"
        }, ensure_ascii=False))
        return 1


def cmd_insert_blocks(args):
    """Insert markdown content at a specific index position in the document.

    This allows inserting new content between existing blocks without
    affecting the rest of the document.
    """
    client = create_client(args.app)

    # Get markdown content
    markdown = _get_markdown_content(args)
    if markdown is None:
        return 1

    block_dicts = markdown_to_blocks(markdown)
    if not block_dicts:
        print(json.dumps({"success": False, "error": "No content to insert"}, ensure_ascii=False))
        return 1

    parent_id = args.parent or args.doc
    index = args.index

    # Split block_dicts into segments: consecutive regular blocks vs table blocks
    segments = []
    current_regular = []

    for bd in block_dicts:
        if bd.get("block_type") == BLOCK_TYPE_TABLE:
            if current_regular:
                segments.append(("regular", current_regular))
                current_regular = []
            segments.append(("table", bd))
        else:
            current_regular.append(bd)

    if current_regular:
        segments.append(("regular", current_regular))

    total_written = 0
    current_index = index

    for seg_type, seg_data in segments:
        if seg_type == "regular":
            # Build Block objects
            children = []
            for bd in seg_data:
                block = Block()
                block.block_type = bd["block_type"]

                for field_name in ["text", "heading1", "heading2", "heading3", "heading4",
                                   "heading5", "heading6", "heading7", "heading8", "heading9",
                                   "bullet", "ordered", "code", "quote", "todo", "divider"]:
                    if field_name in bd:
                        setattr(block, field_name, _dict_to_text(bd[field_name], field_name))
                        break

                children.append(block)

            # Write in batches at the specified index
            BATCH_SIZE = 50
            for batch_start in range(0, len(children), BATCH_SIZE):
                batch = children[batch_start:batch_start + BATCH_SIZE]

                request = CreateDocumentBlockChildrenRequest.builder() \
                    .document_id(args.doc) \
                    .block_id(parent_id) \
                    .request_body(
                        CreateDocumentBlockChildrenRequestBody.builder()
                        .children(batch)
                        .index(current_index)
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
                current_index += len(batch)

        elif seg_type == "table":
            # Table blocks are always appended at the end for now
            ok = _write_table_block(client, args.doc, seg_data, index=current_index)
            if not ok:
                return 1
            total_written += 1
            current_index += 1

    result = {
        "success": True,
        "document_id": args.doc,
        "blocks_inserted": total_written,
        "at_index": index,
        "url": f"https://feishu.cn/docx/{args.doc}"
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


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
    write_parser.add_argument("--mode", choices=["append", "overwrite"], default="append",
                              help="Write mode: append (default) or overwrite (clear first)")

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

    # list-comments
    lc_parser = subparsers.add_parser("list-comments", help="List comments on a document")
    lc_parser.add_argument("--doc", required=True, help="Document ID")
    lc_parser.add_argument("--status", choices=["all", "solved", "unsolved"], default="all",
                           help="Filter by status (default: all)")

    # reply-comment
    rc_parser = subparsers.add_parser("reply-comment", help="Reply to a comment")
    rc_parser.add_argument("--doc", required=True, help="Document ID")
    rc_parser.add_argument("--comment", required=True, help="Comment ID")
    rc_parser.add_argument("--text", required=True, help="Reply text")

    # resolve-comment
    rsc_parser = subparsers.add_parser("resolve-comment", help="Mark a comment as resolved")
    rsc_parser.add_argument("--doc", required=True, help="Document ID")
    rsc_parser.add_argument("--comment", required=True, help="Comment ID")

    # add-comment
    ac_parser = subparsers.add_parser("add-comment", help="Add a new comment to a document")
    ac_parser.add_argument("--doc", required=True, help="Document ID")
    ac_parser.add_argument("--text", required=True, help="Comment text")
    ac_parser.add_argument("--quote", default="", help="Quoted text from document")
    ac_parser.add_argument("--is-whole", action="store_true", help="Comment on whole document")

    # add-member
    am_parser = subparsers.add_parser("add-member", help="Add a collaborator to a document")
    am_parser.add_argument("--doc", required=True, help="Document ID")
    am_parser.add_argument("--open-id", required=True, help="User open_id (ou_xxx)")
    am_parser.add_argument("--perm", choices=["full_access", "edit", "view"],
                           default="full_access", help="Permission level (default: full_access)")

    # patch-block (局部编辑 — 原地更新 block 内容)
    pb_parser = subparsers.add_parser("patch-block",
                                       help="Update a block's text content in-place")
    pb_parser.add_argument("--doc", required=True, help="Document ID")
    pb_parser.add_argument("--block", required=True, help="Block ID to update")
    pb_parser.add_argument("--text", required=True, help="New text content (supports inline markdown)")

    # delete-blocks (局部编辑 — 删除指定范围的 block)
    db_parser = subparsers.add_parser("delete-blocks",
                                       help="Delete a range of child blocks")
    db_parser.add_argument("--doc", required=True, help="Document ID")
    db_parser.add_argument("--start", required=True, type=int, help="Start index (inclusive)")
    db_parser.add_argument("--end", required=True, type=int, help="End index (exclusive)")
    db_parser.add_argument("--parent", help="Parent block ID (default: page block = doc_id)")

    # insert-blocks (局部编辑 — 在指定位置插入内容)
    ib_parser = subparsers.add_parser("insert-blocks",
                                       help="Insert markdown content at a specific index")
    ib_parser.add_argument("--doc", required=True, help="Document ID")
    ib_parser.add_argument("--index", required=True, type=int, help="Insert position (0-based)")
    ib_parser.add_argument("--markdown", help="Markdown content string")
    ib_parser.add_argument("--markdown-file", help="Path to Markdown file")
    ib_parser.add_argument("--parent", help="Parent block ID (default: page block = doc_id)")

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
        "list-comments": cmd_list_comments,
        "reply-comment": cmd_reply_comment,
        "resolve-comment": cmd_resolve_comment,
        "add-comment": cmd_add_comment,
        "add-member": cmd_add_member,
        "patch-block": cmd_patch_block,
        "delete-blocks": cmd_delete_blocks,
        "insert-blocks": cmd_insert_blocks,
    }

    handler = commands.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
