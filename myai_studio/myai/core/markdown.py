"""A small, safe Markdown to HTML renderer.

No third-party dependency is required.  The renderer deliberately escapes all
HTML first, then re-introduces a bounded set of markup, so model output can
never inject scripts into the Qt document.  Supported: headings, paragraphs,
bold/italic/strikethrough, inline code, fenced code blocks with language,
ordered/unordered lists, block quotes, horizontal rules, links and simple
tables.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

_SAFE_SCHEMES = {"http", "https", "mailto"}
_CODE_TOKEN = "\x00CODE{}\x00"
_URL_TOKEN = "\x00URL{}\x00"


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def _is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme.lower() not in _SAFE_SCHEMES:
        return False
    return bool(parsed.netloc or parsed.scheme == "mailto")


def _render_inline(text: str, *, code_store: list[str], url_store: list[str]) -> str:
    # 1. Escape all HTML.
    out = _escape(text)

    # 2. Protect inline code.
    def _code(match: re.Match[str]) -> str:
        code_store.append(_escape(match.group(1).strip()))
        return _CODE_TOKEN.format(len(code_store) - 1)

    out = re.sub(r"`([^`]+)`", _code, out)

    # 3. Links [label](url) with scheme validation.
    def _link(match: re.Match[str]) -> str:
        label, url = match.group(1), html.unescape(match.group(2)).strip()
        if not _is_safe_url(url):
            return label
        url_store.append(_escape(url))
        return f'<a href="{_URL_TOKEN.format(len(url_store) - 1)}">{label}</a>'

    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _link, out)

    # 4. Emphasis (conservative, avoids escaping sequences).
    out = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", out)
    out = re.sub(r"(?<![\w_])_([^_\n]+)_(?![\w_])", r"<i>\1</i>", out)
    out = re.sub(r"~~([^~\n]+)~~", r"<s>\1</s>", out)

    # 5. Restore placeholders.
    for index, code in enumerate(code_store):
        out = out.replace(_CODE_TOKEN.format(index), f"<code>{code}</code>")
    for index, url in enumerate(url_store):
        out = out.replace(_URL_TOKEN.format(index), url)
    return out


def render_markdown(text: str) -> str:
    if text is None:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    blocks: list[str] = []
    paragraph: list[str] = []
    code_store: list[str] = []
    url_store: list[str] = []
    list_stack: list[tuple[int, str]] = []  # (indent, 'ul'|'ol')
    in_blockquote = False
    i = 0

    def inline(value: str) -> str:
        return _render_inline(value, code_store=code_store, url_store=url_store)

    def flush_paragraph() -> None:
        if paragraph:
            content = "<br>".join(inline(line) for line in paragraph)
            blocks.append(f"<p>{content}</p>")
            paragraph.clear()

    def close_lists() -> None:
        while list_stack:
            _, kind = list_stack.pop()
            blocks.append(f"</{kind}>")

    def close_quote() -> None:
        nonlocal in_blockquote
        if in_blockquote:
            blocks.append("</blockquote>")
            in_blockquote = False

    while i < len(lines):
        line = lines[i]

        # fenced code
        fence = re.match(r"^```\s*([\w+#.\-]*)\s*$", line)
        if fence:
            flush_paragraph()
            close_lists()
            close_quote()
            language = fence.group(1)
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not re.match(r"^```\s*$", lines[i]):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            code = _escape("\n".join(code_lines))
            cls = f' class="language-{_escape(language)}"' if language else ""
            blocks.append(f"<pre><code{cls}>{code}</code></pre>")
            continue

        # headings
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            close_lists()
            close_quote()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{inline(heading.group(2).strip())}</h{level}>")
            i += 1
            continue

        # horizontal rule
        if re.match(r"^\s*(?:---+|\*\*\*+|___+)\s*$", line):
            flush_paragraph()
            close_lists()
            close_quote()
            blocks.append("<hr/>")
            i += 1
            continue

        # blockquote
        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            flush_paragraph()
            close_lists()
            if not in_blockquote:
                blocks.append("<blockquote>")
                in_blockquote = True
            blocks.append(f"<p>{inline(quote.group(1))}</p>")
            i += 1
            continue
        else:
            close_quote()

        # tables
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:\-|]+\|[\s:\-|]*$", lines[i + 1]):
            flush_paragraph()
            close_lists()
            header_cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            separator = lines[i + 1]
            alignments: list[str] = []
            for cell in separator.strip().strip("|").split("|"):
                cell = cell.strip()
                if cell.startswith(":") and cell.endswith(":"):
                    alignments.append("center")
                elif cell.endswith(":"):
                    alignments.append("right")
                elif cell.startswith(":"):
                    alignments.append("left")
                else:
                    alignments.append("left")
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append([cell.strip() for cell in lines[i].strip().strip("|").split("|")])
                i += 1
            header_html = "".join(f"<th>{inline(cell)}</th>" for cell in header_cells)
            rows_html = []
            for row in rows:
                cells = []
                for index, cell in enumerate(row):
                    align = alignments[index] if index < len(alignments) else "left"
                    cells.append(f'<td align="{align}">{inline(cell)}</td>')
                rows_html.append(f"<tr>{''.join(cells)}</tr>")
            blocks.append(
                f"<table border='1' cellspacing='0' cellpadding='6' width='100%'>"
                f"<thead><tr>{header_html}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>"
            )
            continue

        # lists
        list_match = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if list_match:
            flush_paragraph()
            indent = len(list_match.group(1).replace("\t", "  "))
            marker = list_match.group(2)
            kind = "ol" if marker[0].isdigit() else "ul"
            while list_stack and indent < list_stack[-1][0]:
                _, closing = list_stack.pop()
                blocks.append(f"</{closing}>")
            if not list_stack or indent > list_stack[-1][0]:
                list_stack.append((indent, kind))
                blocks.append(f"<{kind}>")
            elif list_stack[-1][1] != kind:
                _, closing = list_stack.pop()
                blocks.append(f"</{closing}>")
                list_stack.append((indent, kind))
                blocks.append(f"<{kind}>")
            blocks.append(f"<li>{inline(list_match.group(3))}</li>")
            i += 1
            continue
        else:
            close_lists()

        if not line.strip():
            flush_paragraph()
            close_lists()
            close_quote()
            i += 1
            continue

        paragraph.append(line.strip())
        i += 1

    flush_paragraph()
    close_lists()
    close_quote()
    return "\n".join(blocks)


def plain_text(text: str, limit: int = 200) -> str:
    """Rough markdown stripping for previews and titles."""
    if not text:
        return ""
    value = re.sub(r"```.*?```", " ", text, flags=re.S)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"[*_~#>]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]
