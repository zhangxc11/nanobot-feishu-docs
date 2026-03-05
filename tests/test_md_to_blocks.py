#!/usr/bin/env python3
"""Unit tests for md_to_blocks.py — Markdown → 飞书 Block 转换器"""

import sys
import os
import json

# Add scripts dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from md_to_blocks import (
    markdown_to_blocks,
    _parse_inline_simple,
    _make_text_run,
    _make_text_block,
    _make_divider_block,
    _make_todo_block,
    _estimate_display_width,
    _calculate_column_widths,
    BLOCK_TYPE_TEXT, BLOCK_TYPE_HEADING1, BLOCK_TYPE_HEADING2, BLOCK_TYPE_HEADING3,
    BLOCK_TYPE_BULLET, BLOCK_TYPE_ORDERED, BLOCK_TYPE_CODE, BLOCK_TYPE_QUOTE,
    BLOCK_TYPE_TODO, BLOCK_TYPE_DIVIDER, BLOCK_TYPE_TABLE,
)

import unittest


class TestInlineParsing(unittest.TestCase):
    """Test inline Markdown formatting → TextElement conversion."""

    def test_plain_text(self):
        elements = _parse_inline_simple("Hello world")
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["text_run"]["content"], "Hello world")
        self.assertEqual(elements[0]["text_run"]["text_element_style"], {})

    def test_bold(self):
        elements = _parse_inline_simple("This is **bold** text")
        self.assertEqual(len(elements), 3)
        self.assertEqual(elements[0]["text_run"]["content"], "This is ")
        self.assertEqual(elements[1]["text_run"]["content"], "bold")
        self.assertTrue(elements[1]["text_run"]["text_element_style"]["bold"])
        self.assertEqual(elements[2]["text_run"]["content"], " text")

    def test_italic(self):
        elements = _parse_inline_simple("This is *italic* text")
        self.assertEqual(len(elements), 3)
        self.assertEqual(elements[1]["text_run"]["content"], "italic")
        self.assertTrue(elements[1]["text_run"]["text_element_style"]["italic"])

    def test_strikethrough(self):
        elements = _parse_inline_simple("This is ~~deleted~~ text")
        self.assertEqual(len(elements), 3)
        self.assertEqual(elements[1]["text_run"]["content"], "deleted")
        self.assertTrue(elements[1]["text_run"]["text_element_style"]["strikethrough"])

    def test_inline_code(self):
        elements = _parse_inline_simple("Use `print()` function")
        self.assertEqual(len(elements), 3)
        self.assertEqual(elements[1]["text_run"]["content"], "print()")
        self.assertTrue(elements[1]["text_run"]["text_element_style"]["inline_code"])

    def test_link(self):
        elements = _parse_inline_simple("Visit [Google](https://google.com) now")
        self.assertEqual(len(elements), 3)
        self.assertEqual(elements[1]["text_run"]["content"], "Google")
        self.assertEqual(elements[1]["text_run"]["text_element_style"]["link"]["url"], "https://google.com")

    def test_mixed_formatting(self):
        elements = _parse_inline_simple("**bold** and *italic* and `code`")
        self.assertEqual(len(elements), 5)
        self.assertTrue(elements[0]["text_run"]["text_element_style"]["bold"])
        self.assertTrue(elements[2]["text_run"]["text_element_style"]["italic"])
        self.assertTrue(elements[4]["text_run"]["text_element_style"]["inline_code"])

    def test_empty_text(self):
        elements = _parse_inline_simple("")
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["text_run"]["content"], "")


class TestBlockParsing(unittest.TestCase):
    """Test Markdown line-level → Block conversion."""

    def test_heading1(self):
        blocks = markdown_to_blocks("# Hello")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_HEADING1)
        self.assertEqual(blocks[0]["heading1"]["elements"][0]["text_run"]["content"], "Hello")

    def test_heading2(self):
        blocks = markdown_to_blocks("## World")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_HEADING2)

    def test_heading3(self):
        blocks = markdown_to_blocks("### Section")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_HEADING3)

    def test_paragraph(self):
        blocks = markdown_to_blocks("This is a paragraph.")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_TEXT)
        self.assertEqual(blocks[0]["text"]["elements"][0]["text_run"]["content"], "This is a paragraph.")

    def test_bullet_list(self):
        md = "- Item 1\n- Item 2\n- Item 3"
        blocks = markdown_to_blocks(md)
        self.assertEqual(len(blocks), 3)
        for b in blocks:
            self.assertEqual(b["block_type"], BLOCK_TYPE_BULLET)

    def test_ordered_list(self):
        md = "1. First\n2. Second\n3. Third"
        blocks = markdown_to_blocks(md)
        self.assertEqual(len(blocks), 3)
        for b in blocks:
            self.assertEqual(b["block_type"], BLOCK_TYPE_ORDERED)

    def test_code_block(self):
        md = "```python\nprint('hello')\n```"
        blocks = markdown_to_blocks(md)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_CODE)
        self.assertEqual(blocks[0]["code"]["elements"][0]["text_run"]["content"], "print('hello')")
        self.assertEqual(blocks[0]["code"]["style"]["language"], 49)  # python = 49

    def test_code_block_no_language(self):
        md = "```\nsome code\n```"
        blocks = markdown_to_blocks(md)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_CODE)
        self.assertNotIn("style", blocks[0]["code"])

    def test_quote(self):
        md = "> This is a quote"
        blocks = markdown_to_blocks(md)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_QUOTE)

    def test_multiline_quote(self):
        md = "> Line 1\n> Line 2"
        blocks = markdown_to_blocks(md)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_QUOTE)
        # Content should be joined
        content = blocks[0]["quote"]["elements"][0]["text_run"]["content"]
        self.assertIn("Line 1", content)
        self.assertIn("Line 2", content)

    def test_divider(self):
        blocks = markdown_to_blocks("---")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_DIVIDER)

    def test_divider_variants(self):
        for divider in ["---", "***", "___", "- - -", "* * *"]:
            blocks = markdown_to_blocks(divider)
            self.assertEqual(len(blocks), 1, f"Failed for: {divider}")
            self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_DIVIDER, f"Failed for: {divider}")

    def test_todo_unchecked(self):
        blocks = markdown_to_blocks("- [ ] Buy milk")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_TODO)
        self.assertFalse(blocks[0]["todo"]["style"]["done"])

    def test_todo_checked(self):
        blocks = markdown_to_blocks("- [x] Buy milk")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_TODO)
        self.assertTrue(blocks[0]["todo"]["style"]["done"])

    def test_blank_lines_ignored(self):
        md = "# Title\n\nParagraph\n\n\n- Item"
        blocks = markdown_to_blocks(md)
        self.assertEqual(len(blocks), 3)

    def test_empty_input(self):
        blocks = markdown_to_blocks("")
        self.assertEqual(len(blocks), 0)


class TestComplexDocument(unittest.TestCase):
    """Test full document conversion."""

    def test_full_document(self):
        md = """# Project Report

## Introduction

This is the introduction paragraph with **bold** and *italic* text.

## Features

- Feature 1: Fast processing
- Feature 2: Easy to use
- Feature 3: Reliable

### Code Example

```python
def hello():
    print("Hello, World!")
```

> Note: This is an important note.

---

## Todo

- [x] Design complete
- [ ] Implementation
- [ ] Testing

1. First step
2. Second step
3. Third step
"""
        blocks = markdown_to_blocks(md)

        # Count block types
        types = [b["block_type"] for b in blocks]
        self.assertIn(BLOCK_TYPE_HEADING1, types)
        self.assertIn(BLOCK_TYPE_HEADING2, types)
        self.assertIn(BLOCK_TYPE_HEADING3, types)
        self.assertIn(BLOCK_TYPE_TEXT, types)
        self.assertIn(BLOCK_TYPE_BULLET, types)
        self.assertIn(BLOCK_TYPE_CODE, types)
        self.assertIn(BLOCK_TYPE_QUOTE, types)
        self.assertIn(BLOCK_TYPE_DIVIDER, types)
        self.assertIn(BLOCK_TYPE_TODO, types)
        self.assertIn(BLOCK_TYPE_ORDERED, types)

        # Verify specific counts
        self.assertEqual(types.count(BLOCK_TYPE_HEADING1), 1)  # # Project Report
        self.assertEqual(types.count(BLOCK_TYPE_HEADING2), 3)  # ## Intro, Features, Todo
        self.assertEqual(types.count(BLOCK_TYPE_HEADING3), 1)  # ### Code Example
        self.assertEqual(types.count(BLOCK_TYPE_BULLET), 3)    # 3 features
        self.assertEqual(types.count(BLOCK_TYPE_ORDERED), 3)   # 3 steps
        self.assertEqual(types.count(BLOCK_TYPE_TODO), 3)      # 3 todos
        self.assertEqual(types.count(BLOCK_TYPE_CODE), 1)
        self.assertEqual(types.count(BLOCK_TYPE_QUOTE), 1)
        self.assertEqual(types.count(BLOCK_TYPE_DIVIDER), 1)

    def test_inline_in_blocks(self):
        """Verify inline formatting works within blocks."""
        md = "- **Bold** item with `code` and [link](http://example.com)"
        blocks = markdown_to_blocks(md)
        self.assertEqual(len(blocks), 1)
        elements = blocks[0]["bullet"]["elements"]
        # Should have multiple text_run elements
        self.assertGreater(len(elements), 1)
        # Check bold
        bold_elem = elements[0]
        self.assertTrue(bold_elem["text_run"]["text_element_style"]["bold"])


class TestMakeTextRun(unittest.TestCase):
    """Test _make_text_run helper."""

    def test_plain(self):
        run = _make_text_run("hello")
        self.assertEqual(run["text_run"]["content"], "hello")
        self.assertEqual(run["text_run"]["text_element_style"], {})

    def test_with_styles(self):
        run = _make_text_run("hello", bold=True, italic=True)
        self.assertTrue(run["text_run"]["text_element_style"]["bold"])
        self.assertTrue(run["text_run"]["text_element_style"]["italic"])

    def test_with_link(self):
        run = _make_text_run("click", link_url="https://example.com")
        self.assertEqual(run["text_run"]["text_element_style"]["link"]["url"], "https://example.com")


class TestTableParsing(unittest.TestCase):
    """Test Markdown table → table block dict conversion."""

    def test_simple_table(self):
        md = "| Name | Age |\n|---|---|\n| Alice | 30 |\n| Bob | 25 |"
        blocks = markdown_to_blocks(md)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_TABLE)
        table = blocks[0]["table"]
        self.assertEqual(table["column_size"], 2)
        self.assertEqual(len(table["rows"]), 3)  # header + 2 data rows
        self.assertEqual(table["rows"][0], ["Name", "Age"])
        self.assertEqual(table["rows"][1], ["Alice", "30"])
        self.assertEqual(table["rows"][2], ["Bob", "25"])
        self.assertTrue(table["header_row"])

    def test_table_with_3_columns(self):
        md = "| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |"
        blocks = markdown_to_blocks(md)
        self.assertEqual(len(blocks), 1)
        table = blocks[0]["table"]
        self.assertEqual(table["column_size"], 3)
        self.assertEqual(len(table["rows"]), 2)

    def test_table_with_surrounding_content(self):
        md = "# Title\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nSome text after."
        blocks = markdown_to_blocks(md)
        types = [b["block_type"] for b in blocks]
        self.assertIn(BLOCK_TYPE_HEADING1, types)
        self.assertIn(BLOCK_TYPE_TABLE, types)
        self.assertIn(BLOCK_TYPE_TEXT, types)

    def test_table_uneven_columns(self):
        """Data row with fewer columns than header should be padded."""
        md = "| A | B | C |\n|---|---|---|\n| 1 |"
        blocks = markdown_to_blocks(md)
        table = blocks[0]["table"]
        # Data row should be padded to 3 columns
        self.assertEqual(len(table["rows"][1]), 3)
        self.assertEqual(table["rows"][1][0], "1")
        self.assertEqual(table["rows"][1][1], "")
        self.assertEqual(table["rows"][1][2], "")

    def test_table_with_inline_formatting(self):
        """Table cells can contain inline formatting (handled at write time)."""
        md = "| Name | Desc |\n|---|---|\n| **Bold** | `code` |"
        blocks = markdown_to_blocks(md)
        table = blocks[0]["table"]
        self.assertEqual(table["rows"][1][0], "**Bold**")
        self.assertEqual(table["rows"][1][1], "`code`")

    def test_not_a_table_single_pipe_line(self):
        """A single pipe line without separator should not be parsed as table."""
        md = "| just a line |"
        blocks = markdown_to_blocks(md)
        # Should be parsed as regular text, not a table
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_TEXT)

    def test_table_separator_only(self):
        """Separator without header should not crash."""
        md = "|---|---|\n| 1 | 2 |"
        blocks = markdown_to_blocks(md)
        # First line is separator → divider-like, not a table
        # Should not crash regardless of parsing
        self.assertTrue(len(blocks) >= 1)

    def test_multiple_tables(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |\n\n| X | Y |\n|---|---|\n| 3 | 4 |"
        blocks = markdown_to_blocks(md)
        table_blocks = [b for b in blocks if b["block_type"] == BLOCK_TYPE_TABLE]
        self.assertEqual(len(table_blocks), 2)

    def test_table_with_alignment_markers(self):
        """Separator with alignment markers (:---:, ---:, :---) should work."""
        md = "| Left | Center | Right |\n|:---|:---:|---:|\n| a | b | c |"
        blocks = markdown_to_blocks(md)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["block_type"], BLOCK_TYPE_TABLE)
        table = blocks[0]["table"]
        self.assertEqual(table["column_size"], 3)

    def test_table_has_column_widths(self):
        """Tables should include auto-calculated column_widths."""
        md = "| Name | Age |\n|---|---|\n| Alice | 30 |\n| Bob | 25 |"
        blocks = markdown_to_blocks(md)
        table = blocks[0]["table"]
        self.assertIn("column_widths", table)
        widths = table["column_widths"]
        self.assertEqual(len(widths), 2)
        # Each width should be a positive integer
        for w in widths:
            self.assertIsInstance(w, int)
            self.assertGreaterEqual(w, 80)  # min_col_width
            self.assertLessEqual(w, 400)    # max_col_width

    def test_table_column_widths_proportional(self):
        """Longer content columns should get wider widths."""
        md = "| ID | Description |\n|---|---|\n| 1 | This is a very long description text |"
        blocks = markdown_to_blocks(md)
        widths = blocks[0]["table"]["column_widths"]
        # Description column should be wider than ID column
        self.assertGreater(widths[1], widths[0])

    def test_table_column_widths_cjk(self):
        """CJK characters should count as 2 display width units."""
        md = "| 名称 | Name |\n|---|---|\n| 测试 | Test |"
        blocks = markdown_to_blocks(md)
        widths = blocks[0]["table"]["column_widths"]
        # CJK column "名称"/"测试" (4 display units) vs "Name"/"Test" (4 display units)
        # Should be roughly equal
        self.assertEqual(len(widths), 2)
        # Both should be reasonable widths
        for w in widths:
            self.assertGreaterEqual(w, 80)


class TestDisplayWidthEstimation(unittest.TestCase):
    """Test _estimate_display_width for CJK-aware width calculation."""

    def test_ascii_only(self):
        self.assertEqual(_estimate_display_width("hello"), 5)

    def test_cjk_only(self):
        self.assertEqual(_estimate_display_width("你好"), 4)

    def test_mixed(self):
        self.assertEqual(_estimate_display_width("hello你好"), 9)  # 5 + 4

    def test_empty(self):
        self.assertEqual(_estimate_display_width(""), 0)

    def test_strips_bold_markers(self):
        # **bold** should count as 4, not 8
        self.assertEqual(_estimate_display_width("**bold**"), 4)

    def test_strips_italic_markers(self):
        self.assertEqual(_estimate_display_width("*italic*"), 6)

    def test_strips_code_markers(self):
        self.assertEqual(_estimate_display_width("`code`"), 4)

    def test_strips_link_markers(self):
        # [text](url) should count as len("text") = 4
        self.assertEqual(_estimate_display_width("[text](https://example.com)"), 4)

    def test_strips_strikethrough(self):
        self.assertEqual(_estimate_display_width("~~deleted~~"), 7)


class TestColumnWidthCalculation(unittest.TestCase):
    """Test _calculate_column_widths logic."""

    def test_equal_content(self):
        rows = [["AA", "BB"], ["CC", "DD"]]
        widths = _calculate_column_widths(rows, 2)
        self.assertEqual(len(widths), 2)
        # Equal content → equal widths
        self.assertEqual(widths[0], widths[1])

    def test_unequal_content(self):
        rows = [["A", "BBBBBBBBBBBBBBBBBBBB"]]
        widths = _calculate_column_widths(rows, 2)
        # Longer content column should be wider
        self.assertGreater(widths[1], widths[0])

    def test_min_width_enforced(self):
        rows = [["A", "B"]]
        widths = _calculate_column_widths(rows, 2, total_width=600, min_col_width=80)
        for w in widths:
            self.assertGreaterEqual(w, 80)

    def test_max_width_enforced(self):
        rows = [["A" * 200, "B"]]
        widths = _calculate_column_widths(rows, 2, total_width=600, max_col_width=400)
        for w in widths:
            self.assertLessEqual(w, 400)

    def test_empty_columns(self):
        widths = _calculate_column_widths([], 0)
        self.assertEqual(widths, [])

    def test_three_columns(self):
        rows = [
            ["分类", "含义", "行动"],
            ["🟢 A类", "自包含、可复现、验证明确", "优先构造"],
        ]
        widths = _calculate_column_widths(rows, 3)
        self.assertEqual(len(widths), 3)
        total = sum(widths)
        # Total should be close to 600 (default)
        self.assertGreaterEqual(total, 240)  # 3 * min_col_width
        self.assertLessEqual(total, 1200)    # 3 * max_col_width


if __name__ == "__main__":
    unittest.main()
