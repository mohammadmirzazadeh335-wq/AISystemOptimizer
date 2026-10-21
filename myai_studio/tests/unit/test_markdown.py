from __future__ import annotations

from myai.core.markdown import plain_text, render_markdown


def test_escapes_html() -> None:
    html = render_markdown('<script>alert("x")</script>')
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_blocks_and_inline_formatting() -> None:
    html = render_markdown(
        "# Title\n\nSome **bold** and *italic* and `code`.\n\n- one\n- two\n\n1. first\n2. second\n\n---\n"
    )
    assert "<h1>Title</h1>" in html
    assert "<b>bold</b>" in html
    assert "<i>italic</i>" in html
    assert "<code>code</code>" in html
    assert html.count("<li>") == 4
    assert "<hr/>" in html


def test_fenced_code_is_escaped() -> None:
    html = render_markdown("```python\nprint('<hi>')\n```")
    assert "<pre><code" in html
    assert "&lt;hi&gt;" in html
    assert "language-python" in html


def test_links_only_for_safe_schemes() -> None:
    safe = render_markdown("[docs](https://example.com/x)")
    assert '<a href="https://example.com/x">docs</a>' in safe
    unsafe = render_markdown("[click](javascript:alert(1))")
    assert "javascript:" not in unsafe
    assert "<a" not in unsafe
    relative = render_markdown("[local](file:///etc/passwd)")
    assert "<a" not in relative


def test_table_rendering() -> None:
    html = render_markdown("| a | b |\n| --- | ---: |\n| 1 | 2 |")
    assert "<table" in html and "<th>a</th>" in html and "<td align=\"right\">2</td>" in html


def test_blockquote_and_strikethrough() -> None:
    html = render_markdown("> quoted\n\n~~gone~~")
    assert "<blockquote>" in html and "quoted" in html
    assert "<s>gone</s>" in html


def test_plain_text_strips_markup() -> None:
    assert plain_text("## Hello **world**") == "Hello world"
    assert len(plain_text("x" * 500, limit=10)) == 10
