"""The patch engine: real unified diffs, strict matching, no partial writes."""

from __future__ import annotations

import pytest

from myai.core.errors import ValidationError
from myai.services.patches import apply_replace, apply_unified, parse_unified

ORIGINAL = """def greet(name):
    return f"Hello, {name}"


def farewell(name):
    return f"Bye, {name}"
"""


def test_a_simple_hunk_is_applied() -> None:
    patch = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 def greet(name):
-    return f"Hello, {name}"
+    return f"Hi, {name}"
"""
    updated, hunks = apply_unified(ORIGINAL, patch)
    assert hunks == 1
    assert 'f"Hi, {name}"' in updated
    assert 'f"Hello, {name}"' not in updated
    # The rest of the file is untouched.
    assert "def farewell(name):" in updated


def test_line_numbers_may_drift() -> None:
    """Models usually write an approximate @@ header; context is what matters."""
    shifted = "\n# a comment added earlier\n\n" + ORIGINAL
    patch = """@@ -1,2 +1,2 @@
 def greet(name):
-    return f"Hello, {name}"
+    return f"Hi, {name}"
"""
    updated, _ = apply_unified(shifted, patch)
    assert 'f"Hi, {name}"' in updated
    assert updated.startswith("\n# a comment added earlier")


def test_two_hunks_are_applied_in_order() -> None:
    patch = """@@ -1,2 +1,2 @@
 def greet(name):
-    return f"Hello, {name}"
+    return f"Hi, {name}"
@@ -5,2 +5,2 @@
 def farewell(name):
-    return f"Bye, {name}"
+    return f"See you, {name}"
"""
    updated, hunks = apply_unified(ORIGINAL, patch)
    assert hunks == 2
    assert "Hi, {name}" in updated and "See you, {name}" in updated


def test_a_missing_context_rejects_the_whole_patch() -> None:
    patch = """@@ -1,2 +1,2 @@
 def greet(name):
-    return "not what the file says"
+    return "something else"
"""
    with pytest.raises(ValidationError) as caught:
        apply_unified(ORIGINAL, patch)
    assert caught.value.message_key == "patch.hunk_not_found"
    assert caught.value.context["hunk"] == 1


def test_malformed_input_is_reported_not_guessed() -> None:
    with pytest.raises(ValidationError):
        parse_unified("")
    with pytest.raises(ValidationError):
        parse_unified("hello\nworld\n")
    with pytest.raises(ValidationError):
        parse_unified("@@ -1,1 +1,1 @@\nthis line has no marker\n")
    with pytest.raises(ValidationError):
        # Declares 3 old lines but carries 1.
        parse_unified("@@ -1,3 +1,1 @@\n-old line\n")


def test_replace_requires_a_unique_match() -> None:
    with pytest.raises(ValidationError) as caught:
        apply_replace("x = 1\ny = 1\n", "1", "2")
    assert caught.value.message_key == "patch.find_ambiguous"
    assert caught.value.context["count"] == 2
    updated, count = apply_replace("x = 1\ny = 1\n", "1", "2", replace_all=True)
    assert count == 2 and updated == "x = 2\ny = 2\n"


def test_replace_reports_absent_text() -> None:
    with pytest.raises(ValidationError) as caught:
        apply_replace("abc\n", "zzz", "yyy")
    assert caught.value.message_key == "patch.find_not_found"


def test_replace_accepts_both_newline_spellings() -> None:
    updated, _ = apply_replace("line one\nline two\n", "line one\nline two", "new")
    assert updated == "new\n"
