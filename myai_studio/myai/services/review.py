"""Diff model behind the Review page.

The page never diffs inside a paint event: this module turns two texts into
aligned rows (with intra-line highlight ranges) once, and the widget only draws
what it is given. Everything here is pure Python, so the tricky parts — pairing
a replaced block, clamping huge inputs, keeping a failed patch from writing —
are tested without Qt.

``myai.services.patches`` remains the only code that *applies* a patch; this
module wraps it into a preview the page can show before anything touches disk.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from ..core.errors import AppError
from .patches import apply_unified

#: Rows kept for painting. Beyond this a diff is summarised instead of shown.
MAX_DIFF_ROWS = 4000
#: Character diffs are only meaningful on reasonably short lines.
MAX_INLINE_CHARS = 4000


@dataclass(frozen=True)
class DiffRow:
    """One aligned line pair.

    ``kind`` is ``equal``, ``add``, ``remove`` or ``change``. For ``change``
    both texts are present and ``old_spans``/``new_spans`` mark the characters
    that differ, so the widget can underline the words that actually moved.
    """

    kind: str
    old_no: int | None
    new_no: int | None
    old_text: str
    new_text: str
    old_spans: tuple[tuple[int, int], ...] = ()
    new_spans: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class DiffStats:
    added: int = 0
    removed: int = 0
    changed: int = 0
    equal: int = 0

    @property
    def changed_lines(self) -> int:
        return self.added + self.removed + self.changed

    @property
    def similarity(self) -> float:
        total = self.added + self.removed + self.changed + self.equal
        return round(self.equal / total, 3) if total else 1.0


@dataclass(frozen=True)
class DiffResult:
    rows: tuple[DiffRow, ...] = ()
    stats: DiffStats = field(default_factory=DiffStats)
    truncated: bool = False
    identical: bool = False


@dataclass(frozen=True)
class PatchPreview:
    """Result of applying a patch in memory — never a write."""

    ok: bool
    hunks: int = 0
    updated: str = ""
    error: str = ""
    message_key: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "hunks": self.hunks,
            "error": self.error,
            "message_key": self.message_key,
        }


def _coalesce(ranges: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def inline_spans(old: str, new: str) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    """Character ranges that differ between two lines (empty if too long)."""
    if len(old) > MAX_INLINE_CHARS or len(new) > MAX_INLINE_CHARS:
        return (), ()
    if old == new:
        return (), ()
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    old_ranges: list[tuple[int, int]] = []
    new_ranges: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            old_ranges.append((i1, i2))
        if j2 > j1:
            new_ranges.append((j1, j2))
    return _coalesce(old_ranges), _coalesce(new_ranges)


def compare_texts(old: str, new: str, *, max_rows: int = MAX_DIFF_ROWS) -> DiffResult:
    """Align two texts into rows and count what changed."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    opcodes = matcher.get_opcodes()

    equal = added = removed = changed = 0
    rows: list[DiffRow] = []
    truncated = False

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            equal += i2 - i1
            for offset in range(i2 - i1):
                if len(rows) >= max_rows:
                    truncated = True
                    continue
                rows.append(
                    DiffRow("equal", i1 + offset + 1, j1 + offset + 1, old_lines[i1 + offset], old_lines[i1 + offset])
                )
        elif tag == "delete":
            removed += i2 - i1
            for offset in range(i2 - i1):
                if len(rows) >= max_rows:
                    truncated = True
                    continue
                rows.append(DiffRow("remove", i1 + offset + 1, None, old_lines[i1 + offset], ""))
        elif tag == "insert":
            added += j2 - j1
            for offset in range(j2 - j1):
                if len(rows) >= max_rows:
                    truncated = True
                    continue
                rows.append(DiffRow("add", None, j1 + offset + 1, "", new_lines[j1 + offset]))
        else:  # replace: pair what we can, the remainder is a pure add or remove
            old_block = old_lines[i1:i2]
            new_block = new_lines[j1:j2]
            paired = min(len(old_block), len(new_block))
            changed += paired
            removed += len(old_block) - paired
            added += len(new_block) - paired
            for offset in range(paired):
                old_line = old_block[offset]
                new_line = new_block[offset]
                spans = inline_spans(old_line, new_line)
                if len(rows) < max_rows:
                    rows.append(
                        DiffRow(
                            "change",
                            i1 + offset + 1,
                            j1 + offset + 1,
                            old_line,
                            new_line,
                            spans[0],
                            spans[1],
                        )
                    )
                else:
                    truncated = True
            for offset in range(paired, len(old_block)):
                if len(rows) >= max_rows:
                    truncated = True
                    continue
                rows.append(DiffRow("remove", i1 + offset + 1, None, old_block[offset], ""))
            for offset in range(paired, len(new_block)):
                if len(rows) >= max_rows:
                    truncated = True
                    continue
                rows.append(DiffRow("add", None, j1 + offset + 1, "", new_block[offset]))

    stats = DiffStats(added=added, removed=removed, changed=changed, equal=equal)
    return DiffResult(
        rows=tuple(rows),
        stats=stats,
        truncated=truncated,
        identical=not (added or removed or changed),
    )


def unified_diff(old: str, new: str, old_name: str = "a", new_name: str = "b") -> str:
    """Real unified diff text, suitable for saving or sending back to a model."""
    lines = difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile=old_name,
        tofile=new_name,
        lineterm="",
    )
    return "\n".join(lines)


def preview_patch(text: str, patch: str) -> PatchPreview:
    """Apply a patch to a string; return the result or the exact reason."""
    if not patch.strip():
        return PatchPreview(False, error="The patch is empty.", message_key="review.patch_empty")
    try:
        updated, hunks = apply_unified(text, patch)
    except AppError as exc:
        return PatchPreview(
            False,
            error=str(exc),
            message_key=getattr(exc, "message_key", "") or "review.patch_failed",
        )
    return PatchPreview(True, hunks=hunks, updated=updated)


def language_of(path: str) -> str:
    lower = path.lower()
    if lower.endswith((".py", ".pyw")):
        return "python"
    if lower.endswith((".js", ".mjs", ".cjs", ".jsx")):
        return "javascript"
    if lower.endswith((".ts", ".tsx")):
        return "typescript"
    if lower.endswith((".c", ".h")):
        return "c"
    if lower.endswith((".cpp", ".cc", ".cxx", ".hpp")):
        return "cpp"
    if lower.endswith((".json",)):
        return "json"
    if lower.endswith((".md", ".markdown")):
        return "markdown"
    return "text"


__all__ = [
    "DiffResult",
    "DiffRow",
    "DiffStats",
    "PatchPreview",
    "compare_texts",
    "inline_spans",
    "language_of",
    "preview_patch",
    "unified_diff",
]
