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
    BLOCK_TYPE_TEXT, BLOCK_TYPE_HEADING1, BLOCK_TYPE_HEADING2, BLOCK_TYPE_HEADING3,
    BLOCK_TYPE_BULLET, BLOCK_TYPE_ORDERED, BLOCK_TYPE_CODE, BLOCK_TYPE_QUOTE,
    BLOCK_TYPE_TODO, BLOCK_TYPE_DIVIDER,
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


if __name__ == "__main__":
    unittest.main()
