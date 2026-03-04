#!/usr/bin/env python3
"""Markdown → 飞书 Block 转换器

将 Markdown 文本解析为飞书文档 Block 数据结构（dict 列表），
可直接用于 lark-oapi SDK 的 create_document_block_children API。

飞书 Block 类型参考:
  1  = page (文档根节点)
  2  = text (普通段落)
  3  = heading1
  4  = heading2
  5  = heading3
  6  = heading4
  7  = heading5
  8  = heading6
  9  = heading7
  10 = heading8
  11 = heading9
  12 = bullet (无序列表)
  13 = ordered (有序列表)
  14 = code (代码块)
  15 = quote (引用)
  17 = todo (待办事项)
  22 = divider (分割线)
"""

import re
from typing import List, Dict, Any, Optional


# ── Block type constants ──────────────────────────────────────────────

BLOCK_TYPE_PAGE = 1
BLOCK_TYPE_TEXT = 2
BLOCK_TYPE_HEADING1 = 3
BLOCK_TYPE_HEADING2 = 4
BLOCK_TYPE_HEADING3 = 5
BLOCK_TYPE_HEADING4 = 6
BLOCK_TYPE_HEADING5 = 7
BLOCK_TYPE_HEADING6 = 8
BLOCK_TYPE_HEADING7 = 9
BLOCK_TYPE_HEADING8 = 10
BLOCK_TYPE_HEADING9 = 11
BLOCK_TYPE_BULLET = 12
BLOCK_TYPE_ORDERED = 13
BLOCK_TYPE_CODE = 14
BLOCK_TYPE_QUOTE = 15
BLOCK_TYPE_TODO = 17
BLOCK_TYPE_DIVIDER = 22
BLOCK_TYPE_TABLE = 31


# ── Inline style parsing ─────────────────────────────────────────────

def _parse_inline_elements(text: str) -> List[Dict[str, Any]]:
    """Parse inline Markdown formatting into Feishu TextElement list.

    Supports: **bold**, *italic*, ~~strikethrough~~, `inline_code`, [text](url)

    Returns a list of dicts, each representing a TextElement:
    {
        "text_run": {
            "content": "...",
            "text_element_style": { "bold": true, ... }
        }
    }
    """
    elements = []

    # Pattern to match inline formatting tokens
    # Order matters: longer patterns first to avoid partial matches
    # We use a state-machine approach: scan left to right, match tokens
    patterns = [
        # [text](url) — link
        (r'\[([^\]]+)\]\(([^)]+)\)', 'link'),
        # **bold** or __bold__
        (r'\*\*(.+?)\*\*|__(.+?)__', 'bold'),
        # *italic* or _italic_ (but not inside words for _)
        (r'\*(.+?)\*|(?<!\w)_(.+?)_(?!\w)', 'italic'),
        # ~~strikethrough~~
        (r'~~(.+?)~~', 'strikethrough'),
        # `inline_code`
        (r'`([^`]+)`', 'inline_code'),
    ]

    # Combined regex: capture all inline tokens
    combined = '|'.join(f'({p[0]})' for p in patterns)
    token_types = [p[1] for p in patterns]

    pos = 0
    for match in re.finditer(combined, text):
        # Add plain text before this match
        if match.start() > pos:
            plain = text[pos:match.start()]
            if plain:
                elements.append(_make_text_run(plain))

        # Determine which pattern matched
        group_idx = 0
        matched_type = None
        for i, (pattern, ptype) in enumerate(patterns):
            # Each pattern contributes some groups to the combined regex
            # We need to find which top-level group is non-None
            top_group = match.group(group_idx + 1)
            if top_group is not None:
                matched_type = ptype
                # Extract the inner content based on type
                inner_match = re.match(pattern, top_group)
                if matched_type == 'link':
                    link_text = inner_match.group(1)
                    link_url = inner_match.group(2)
                    elements.append(_make_text_run(link_text, link_url=link_url))
                elif matched_type == 'bold':
                    content = inner_match.group(1) or inner_match.group(2)
                    elements.append(_make_text_run(content, bold=True))
                elif matched_type == 'italic':
                    content = inner_match.group(1) or inner_match.group(2)
                    elements.append(_make_text_run(content, italic=True))
                elif matched_type == 'strikethrough':
                    content = inner_match.group(1)
                    elements.append(_make_text_run(content, strikethrough=True))
                elif matched_type == 'inline_code':
                    content = inner_match.group(1)
                    elements.append(_make_text_run(content, inline_code=True))
                break
            # Count groups in this pattern to advance
            group_idx += 1 + re.compile(pattern).groups

        pos = match.end()

    # Add remaining plain text
    if pos < len(text):
        remaining = text[pos:]
        if remaining:
            elements.append(_make_text_run(remaining))

    # If no elements were created (empty text or no matches), return single text_run
    if not elements and text:
        elements.append(_make_text_run(text))

    return elements


def _parse_inline_simple(text: str) -> List[Dict[str, Any]]:
    """Simplified inline parser using sequential regex replacements.

    More robust than the combined-regex approach. Processes text left-to-right,
    extracting formatted segments.
    """
    if not text:
        return [_make_text_run("")]

    elements = []
    # Tokenize: find all inline formatting spans
    # We'll use a simple approach: find tokens, split text around them

    # Token pattern: matches all inline formatting
    token_re = re.compile(
        r'(\[([^\]]+)\]\(([^)]+)\))'   # [text](url)
        r'|(\*\*(.+?)\*\*)'            # **bold**
        r'|(~~(.+?)~~)'                 # ~~strike~~
        r'|(`([^`]+)`)'                 # `code`
        r'|(\*(.+?)\*)'                 # *italic*
    )

    pos = 0
    for m in token_re.finditer(text):
        # Plain text before match
        if m.start() > pos:
            elements.append(_make_text_run(text[pos:m.start()]))

        if m.group(1):  # link
            elements.append(_make_text_run(m.group(2), link_url=m.group(3)))
        elif m.group(4):  # bold
            elements.append(_make_text_run(m.group(5), bold=True))
        elif m.group(6):  # strikethrough
            elements.append(_make_text_run(m.group(7), strikethrough=True))
        elif m.group(8):  # inline code
            elements.append(_make_text_run(m.group(9), inline_code=True))
        elif m.group(10):  # italic
            elements.append(_make_text_run(m.group(11), italic=True))

        pos = m.end()

    # Remaining text
    if pos < len(text):
        elements.append(_make_text_run(text[pos:]))

    if not elements:
        elements.append(_make_text_run(text))

    return elements


def _make_text_run(content: str, bold: bool = False, italic: bool = False,
                   strikethrough: bool = False, inline_code: bool = False,
                   link_url: Optional[str] = None) -> Dict[str, Any]:
    """Create a Feishu TextElement (text_run) dict."""
    style = {}
    if bold:
        style["bold"] = True
    if italic:
        style["italic"] = True
    if strikethrough:
        style["strikethrough"] = True
    if inline_code:
        style["inline_code"] = True
    if link_url:
        style["link"] = {"url": link_url}

    element = {
        "text_run": {
            "content": content,
            "text_element_style": style
        }
    }
    return element


# ── Block construction helpers ────────────────────────────────────────

def _make_text_block(block_type: int, text: str, code_language: Optional[int] = None) -> Dict[str, Any]:
    """Create a Feishu Block dict with text content.

    Args:
        block_type: Feishu block type constant
        text: Markdown-formatted text content
        code_language: Language enum for code blocks (optional)
    """
    elements = _parse_inline_simple(text)

    # Determine the block field name from block_type
    field_map = {
        BLOCK_TYPE_TEXT: "text",
        BLOCK_TYPE_HEADING1: "heading1",
        BLOCK_TYPE_HEADING2: "heading2",
        BLOCK_TYPE_HEADING3: "heading3",
        BLOCK_TYPE_HEADING4: "heading4",
        BLOCK_TYPE_HEADING5: "heading5",
        BLOCK_TYPE_HEADING6: "heading6",
        BLOCK_TYPE_HEADING7: "heading7",
        BLOCK_TYPE_HEADING8: "heading8",
        BLOCK_TYPE_HEADING9: "heading9",
        BLOCK_TYPE_BULLET: "bullet",
        BLOCK_TYPE_ORDERED: "ordered",
        BLOCK_TYPE_CODE: "code",
        BLOCK_TYPE_QUOTE: "quote",
        BLOCK_TYPE_TODO: "todo",
    }

    field_name = field_map.get(block_type, "text")

    block: Dict[str, Any] = {
        "block_type": block_type,
        field_name: {
            "elements": elements
        }
    }

    # Add code language if applicable
    if block_type == BLOCK_TYPE_CODE and code_language is not None:
        block[field_name]["style"] = {"language": code_language}

    return block


def _make_divider_block() -> Dict[str, Any]:
    """Create a Feishu divider Block dict."""
    return {
        "block_type": BLOCK_TYPE_DIVIDER,
        "divider": {}
    }


def _make_todo_block(text: str, done: bool = False) -> Dict[str, Any]:
    """Create a Feishu todo Block dict."""
    elements = _parse_inline_simple(text)
    block: Dict[str, Any] = {
        "block_type": BLOCK_TYPE_TODO,
        "todo": {
            "elements": elements,
            "style": {
                "done": done
            }
        }
    }
    return block


# ── Table parsing helpers ─────────────────────────────────────────────

def _is_table_row(line: str) -> bool:
    """Check if a line looks like a Markdown table row: | ... | ... |"""
    stripped = line.strip()
    return stripped.startswith('|') and stripped.endswith('|') and stripped.count('|') >= 2


def _is_separator_row(line: str) -> bool:
    """Check if a line is a Markdown table separator: |---|---|"""
    stripped = line.strip()
    if not stripped.startswith('|') or not stripped.endswith('|'):
        return False
    # Remove leading/trailing pipes, split by |
    cells = stripped[1:-1].split('|')
    for cell in cells:
        cell = cell.strip()
        # Separator cells: ---, :---, ---:, :---:
        if not re.match(r'^:?-{1,}:?$', cell):
            return False
    return True


def _is_table_start(lines: List[str], i: int) -> bool:
    """Check if position i starts a Markdown table (header + separator + at least 1 data row)."""
    if i + 1 >= len(lines):
        return False
    line = lines[i]
    next_line = lines[i + 1]
    return _is_table_row(line) and _is_separator_row(next_line)


def _parse_table_row_cells(line: str) -> List[str]:
    """Parse a table row line into cell content strings."""
    stripped = line.strip()
    # Remove leading/trailing pipes
    if stripped.startswith('|'):
        stripped = stripped[1:]
    if stripped.endswith('|'):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split('|')]


def _estimate_display_width(text: str) -> int:
    """Estimate the display width of text content.

    CJK characters count as 2 units, ASCII characters count as 1.
    Inline markdown markers (**, *, ~~, `) are stripped before counting.
    """
    # Strip inline markdown markers for width estimation
    stripped = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    stripped = re.sub(r'\*(.+?)\*', r'\1', stripped)
    stripped = re.sub(r'~~(.+?)~~', r'\1', stripped)
    stripped = re.sub(r'`([^`]+)`', r'\1', stripped)
    stripped = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', stripped)

    width = 0
    for ch in stripped:
        if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f' or \
           '\uff00' <= ch <= '\uffef' or '\u3400' <= ch <= '\u4dbf':
            width += 2
        else:
            width += 1
    return width


def _calculate_column_widths(rows: List[List[str]], col_count: int,
                             total_width: int = 600,
                             min_col_width: int = 80,
                             max_col_width: int = 400) -> List[int]:
    """Calculate appropriate column widths based on cell content.

    Strategy:
    1. For each column, find the maximum display width across all rows
    2. Use square root of content width for proportional allocation
       (compresses the ratio between long and short columns for better visual balance)
    3. Distribute total_width proportionally
    4. Clamp each column to [min_col_width, max_col_width]

    Args:
        rows: List of rows, each row is a list of cell content strings
        col_count: Number of columns
        total_width: Target total table width in px (default 600)
        min_col_width: Minimum column width in px
        max_col_width: Maximum column width in px

    Returns:
        List of column widths (integers)
    """
    if col_count == 0:
        return []

    import math

    # Calculate max content width for each column
    col_max_widths = [0] * col_count
    for row in rows:
        for col_idx in range(min(len(row), col_count)):
            w = _estimate_display_width(row[col_idx])
            if w > col_max_widths[col_idx]:
                col_max_widths[col_idx] = w

    # Ensure minimum content width of 1 to avoid division by zero
    col_max_widths = [max(w, 1) for w in col_max_widths]

    # Use square root for more balanced proportional allocation
    sqrt_widths = [math.sqrt(w) for w in col_max_widths]
    total_sqrt = sum(sqrt_widths)

    # Proportional allocation based on sqrt
    raw_widths = [(sw / total_sqrt) * total_width for sw in sqrt_widths]

    # Clamp to [min_col_width, max_col_width]
    widths = [max(min_col_width, min(max_col_width, int(round(w)))) for w in raw_widths]

    return widths


def _parse_table(lines: List[str], i: int) -> tuple:
    """Parse a Markdown table starting at line i.

    Returns:
        (table_block_dict, next_line_index)
    """
    rows = []

    # Parse header row
    header_cells = _parse_table_row_cells(lines[i])
    rows.append(header_cells)
    col_count = len(header_cells)
    i += 1

    # Skip separator row
    if i < len(lines) and _is_separator_row(lines[i]):
        i += 1

    # Parse data rows
    while i < len(lines) and _is_table_row(lines[i]) and not _is_separator_row(lines[i]):
        cells = _parse_table_row_cells(lines[i])
        # Pad or trim to match column count
        while len(cells) < col_count:
            cells.append("")
        cells = cells[:col_count]
        rows.append(cells)
        i += 1

    # Calculate appropriate column widths based on content
    column_widths = _calculate_column_widths(rows, col_count)

    # Build table block dict
    table_block: Dict[str, Any] = {
        "block_type": BLOCK_TYPE_TABLE,
        "table": {
            "rows": rows,
            "column_size": col_count,
            "header_row": True,
            "column_widths": column_widths,
        }
    }

    return table_block, i


# ── Code language mapping ─────────────────────────────────────────────

# Feishu code block language enum values
CODE_LANGUAGES = {
    "plaintext": 1, "abap": 2, "ada": 3, "apache": 4, "apex": 5,
    "assembly": 6, "bash": 7, "shell": 7, "sh": 7, "csharp": 8, "c#": 8,
    "cpp": 9, "c++": 9, "c": 10, "cobol": 11, "css": 12, "coffeescript": 13,
    "d": 14, "dart": 15, "delphi": 16, "django": 17, "dockerfile": 18,
    "erlang": 19, "fortran": 20, "foxpro": 21, "go": 22, "golang": 22,
    "groovy": 23, "html": 24, "htmlbars": 25, "http": 26, "haskell": 27,
    "json": 28, "java": 29, "javascript": 30, "js": 30, "julia": 31,
    "kotlin": 32, "latex": 33, "lisp": 34, "lua": 36, "matlab": 37,
    "makefile": 38, "markdown": 39, "md": 39, "nginx": 40, "objectivec": 41,
    "objective-c": 41, "openedgeabl": 42, "php": 43, "perl": 44,
    "powershell": 46, "prolog": 47, "protobuf": 48, "python": 49, "py": 49,
    "r": 50, "rpg": 51, "ruby": 52, "rb": 52, "rust": 53, "rs": 53,
    "sas": 54, "scss": 55, "sql": 56, "scala": 57, "scheme": 58,
    "scratch": 59, "swift": 60, "thrift": 61, "typescript": 62, "ts": 62,
    "vbscript": 63, "visual basic": 64, "vb": 64, "xml": 65, "yaml": 66,
    "yml": 66, "cmake": 67, "ansi": 68,
}


# ── Main parser ───────────────────────────────────────────────────────

def markdown_to_blocks(markdown_text: str) -> List[Dict[str, Any]]:
    """Convert Markdown text to a list of Feishu Block dicts.

    Args:
        markdown_text: Markdown-formatted text

    Returns:
        List of Block dicts ready for Feishu API
    """
    lines = markdown_text.split('\n')
    blocks: List[Dict[str, Any]] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # ── Blank line → empty text block (preserves paragraph spacing) ──
        # Only insert an empty block between two text paragraphs to create
        # visible spacing.  Blank lines after headings, lists, etc. are just
        # Markdown syntax separators and should not produce extra blocks.
        if not line.strip():
            if (blocks
                    and blocks[-1].get("block_type") == BLOCK_TYPE_TEXT
                    and blocks[-1].get("text", {}).get("elements", [{}])[0]
                        .get("text_run", {}).get("content", "") != ""):
                # Peek ahead: only add empty block if the next non-blank line
                # is also a plain paragraph (text block).
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    next_line = lines[j]
                    is_next_paragraph = (
                        next_line.strip()
                        and not next_line.strip().startswith('#')
                        and not next_line.strip().startswith('```')
                        and not re.match(r'^[-*+]\s', next_line)
                        and not re.match(r'^\d+\.\s', next_line)
                        and not next_line.startswith('>')
                        and not re.match(r'^(\s*[-*_]\s*){3,}$', next_line)
                        and not re.match(r'^[-*]\s+\[[ xX]\]', next_line)
                    )
                    if is_next_paragraph:
                        blocks.append(_make_text_block(BLOCK_TYPE_TEXT, ""))
            i += 1
            continue

        # ── Divider: --- or *** or ___ (3+ chars) ──
        if re.match(r'^(\s*[-*_]\s*){3,}$', line):
            blocks.append(_make_divider_block())
            i += 1
            continue

        # ── Table: | col1 | col2 | ──
        if _is_table_start(lines, i):
            table_block, i = _parse_table(lines, i)
            if table_block:
                blocks.append(table_block)
            continue

        # ── Code block: ``` ──
        if line.strip().startswith('```'):
            lang_str = line.strip()[3:].strip().lower()
            code_lang = CODE_LANGUAGES.get(lang_str)
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1  # skip closing ```

            code_content = '\n'.join(code_lines)
            # Code blocks use plain text_run, no inline formatting
            block: Dict[str, Any] = {
                "block_type": BLOCK_TYPE_CODE,
                "code": {
                    "elements": [_make_text_run(code_content)]
                }
            }
            if code_lang is not None:
                block["code"]["style"] = {"language": code_lang}
            blocks.append(block)
            continue

        # ── Heading: # ~ ######### ──
        heading_match = re.match(r'^(#{1,9})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            content = heading_match.group(2).strip()
            block_type = BLOCK_TYPE_HEADING1 + level - 1  # heading1=3, heading2=4, ...
            blocks.append(_make_text_block(block_type, content))
            i += 1
            continue

        # ── Todo: - [ ] or - [x] ──
        todo_match = re.match(r'^[-*]\s+\[([ xX])\]\s+(.+)$', line)
        if todo_match:
            done = todo_match.group(1).lower() == 'x'
            content = todo_match.group(2).strip()
            blocks.append(_make_todo_block(content, done=done))
            i += 1
            continue

        # ── Unordered list: - item or * item ──
        bullet_match = re.match(r'^[-*+]\s+(.+)$', line)
        if bullet_match:
            content = bullet_match.group(1).strip()
            blocks.append(_make_text_block(BLOCK_TYPE_BULLET, content))
            i += 1
            continue

        # ── Ordered list: 1. item ──
        ordered_match = re.match(r'^\d+\.\s+(.+)$', line)
        if ordered_match:
            content = ordered_match.group(1).strip()
            blocks.append(_make_text_block(BLOCK_TYPE_ORDERED, content))
            i += 1
            continue

        # ── Quote: > text ──
        if line.startswith('>'):
            # Collect consecutive quote lines
            quote_lines = []
            while i < len(lines) and lines[i].startswith('>'):
                quote_lines.append(re.sub(r'^>\s?', '', lines[i]))
                i += 1
            content = '\n'.join(quote_lines).strip()
            blocks.append(_make_text_block(BLOCK_TYPE_QUOTE, content))
            continue

        # ── Regular paragraph ──
        # Collect consecutive non-empty, non-special lines as one paragraph
        para_lines = [line]
        i += 1
        while i < len(lines):
            next_line = lines[i]
            # Stop at blank line or special syntax
            if (not next_line.strip() or
                next_line.strip().startswith('#') or
                next_line.strip().startswith('```') or
                re.match(r'^[-*+]\s', next_line) or
                re.match(r'^\d+\.\s', next_line) or
                next_line.startswith('>') or
                re.match(r'^(\s*[-*_]\s*){3,}$', next_line) or
                re.match(r'^[-*]\s+\[[ xX]\]', next_line)):
                break
            para_lines.append(next_line)
            i += 1

        content = ' '.join(para_lines).strip()
        if content:
            blocks.append(_make_text_block(BLOCK_TYPE_TEXT, content))

    return blocks


# ── Utility: blocks to JSON for API ──────────────────────────────────

def blocks_to_api_json(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert block dicts to the format expected by Feishu API.

    This is essentially the same format, but ensures all required fields
    are present and properly structured.
    """
    return blocks


# ── CLI for testing ──────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) > 1:
        # Read from file
        with open(sys.argv[1], 'r') as f:
            md = f.read()
    else:
        # Read from stdin
        md = sys.stdin.read()

    blocks = markdown_to_blocks(md)
    print(json.dumps(blocks, ensure_ascii=False, indent=2))
