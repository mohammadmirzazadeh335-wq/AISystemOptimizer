"""Review service: alignment, intra-line spans, clamping and patch preview."""

from __future__ import annotations

from myai.services.review import (
    MAX_DIFF_ROWS,
    compare_texts,
    inline_spans,
    language_of,
    preview_patch,
    unified_diff,
)

OLD = """def greet(name):
    print('hello', name)
    return name

print(greet('Ada'))
"""
NEW = """def greet(name: str) -> str:
    print(f'hello {name}')
    return name

print(greet('Ada'))
print('done')
"""


# ------------------------------------------------------------------ alignment
def test_identical_texts_have_no_changes() -> None:
    result = compare_texts("a\nb\n", "a\nb\n")
    assert result.identical
    assert result.stats.changed_lines == 0
    assert [row.kind for row in result.rows] == ["equal", "equal"]


def test_replacements_are_paired_as_change_rows() -> None:
    result = compare_texts("a\nb\nc\n", "a\nB\nc\n")
    kinds = [row.kind for row in result.rows]
    assert kinds == ["equal", "change", "equal"]
    row = result.rows[1]
    assert row.old_text == "b" and row.new_text == "B"
    assert row.old_no == 2 and row.new_no == 2
    assert result.stats.changed == 1
    assert result.stats.similarity == 0.667


def test_unpaired_lines_become_add_or_remove() -> None:
    result = compare_texts("keep\nold1\nold2\n", "keep\nnew1\n")
    kinds = [row.kind for row in result.rows]
    assert kinds == ["equal", "change", "remove"]
    assert result.stats.removed == 1
    assert result.stats.changed == 1


def test_pure_insert_and_delete() -> None:
    added = compare_texts("a\n", "a\nb\nc\n")
    assert added.stats.added == 2 and added.stats.removed == 0
    assert [row.new_no for row in added.rows if row.kind == "add"] == [2, 3]
    deleted = compare_texts("a\nb\n", "a\n")
    assert deleted.stats.removed == 1
    assert deleted.rows[-1].old_no == 2 and deleted.rows[-1].new_no is None


def test_line_numbers_survive_reorder() -> None:
    result = compare_texts("one\ntwo\nthree\n", "three\none\ntwo\n")
    equal_rows = [row for row in result.rows if row.kind == "equal"]
    assert equal_rows, "a move still contains equal lines"
    for row in equal_rows:
        assert row.old_text == row.new_text


def test_long_input_is_clamped_and_flagged() -> None:
    lines = [f"line {index}" for index in range(MAX_DIFF_ROWS + 50)]
    old = "\n".join(lines)
    lines[5] = "line five"
    new = "\n".join(lines)
    result = compare_texts(old, new)
    assert result.truncated is True
    assert len(result.rows) <= MAX_DIFF_ROWS
    # Stats still describe the whole input, not just the painted window.
    assert result.stats.changed == 1


# -------------------------------------------------------------- inline spans
def test_inline_spans_mark_only_the_changed_words() -> None:
    old_spans, new_spans = inline_spans("print('hello', name)", "print(f'hello {name}')")
    assert old_spans and new_spans
    assert all(0 <= start < end <= len("print('hello', name)") for start, end in old_spans)
    assert all(0 <= start < end <= len("print(f'hello {name}')") for start, end in new_spans)


def test_insertion_has_no_span_on_the_old_side() -> None:
    old_spans, new_spans = inline_spans("def f():", "def f() -> None:")
    assert old_spans == ()
    assert new_spans == ((7, 15),)


def test_very_long_lines_skip_inline_diff() -> None:
    old = "x" * 5000
    new = "y" * 5000
    assert inline_spans(old, new) == ((), ())


def test_spans_are_sorted_and_merged() -> None:
    old_spans, new_spans = inline_spans("aaaa bbbb cccc", "aaaa XXXX cccc")
    assert list(old_spans) == sorted(old_spans)
    assert list(new_spans) == sorted(new_spans)


# ------------------------------------------------------------------- patches
def test_patch_preview_applies_in_memory() -> None:
    patch = "--- a\n+++ b\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"
    preview = preview_patch("a\nb\nc\n", patch)
    assert preview.ok and preview.hunks == 1
    assert preview.updated == "a\nB\nc\n"


def test_failed_patch_reports_the_reason_and_changes_nothing() -> None:
    preview = preview_patch("a\nb\n", "--- a\n+++ b\n@@ -1,2 +1,2 @@\n nope\n-b\n+c\n")
    assert not preview.ok
    assert preview.updated == ""
    assert preview.message_key == "patch.hunk_not_found"
    assert "does not match" in preview.error


def test_empty_patch_is_refused() -> None:
    preview = preview_patch("a\n", "   \n")
    assert not preview.ok
    assert preview.message_key == "review.patch_empty"


def test_unified_diff_round_trips_through_the_patch_engine() -> None:
    patch = unified_diff("a\nb\n", "a\nB\n", "old.py", "new.py")
    assert patch.startswith("--- old.py")
    assert "+++ new.py" in patch
    preview = preview_patch("a\nb\n", patch)
    assert preview.ok and preview.updated == "a\nB\n"


# ------------------------------------------------------------------ language
def test_language_of_common_extensions() -> None:
    assert language_of("a.py") == "python"
    assert language_of("a.tsx") == "typescript"
    assert language_of("a.js") == "javascript"
    assert language_of("README.md") == "markdown"
    assert language_of("notes") == "text"
