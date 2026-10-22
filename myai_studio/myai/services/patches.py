"""Apply a unified diff (or a literal replacement) to real file text.

Why not ``subprocess`` + ``patch``? Windows has no ``patch.exe`` by default, and
the agent runs inside a sandbox where spawning a tool for every edit would be
slow and hard to bound. More importantly, a patch tool must be *predictable*:
this module never writes anything (the caller does, atomically) and it refuses
to guess. Concretely:

* a hunk is applied at the first place at or after the current position where
  its **exact** context matches — so line numbers that drifted by a few lines
  still work, which is the most common real failure of model-written patches;
* if the context is missing the whole patch is rejected with the hunk number and
  the first expected line, and the file is left untouched;
* a replacement whose search text matches twice is rejected unless ``replace_all``
  is explicit — silently editing two functions is never acceptable.

Everything here is pure text → text, which is why it is easy to test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.errors import ValidationError

_HUNK_RE = re.compile(
    r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$"
)
_STOP_PREFIXES = ("--- ", "+++ ", "diff ", "index ", "*** ")


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: tuple[tuple[str, str], ...]

    @property
    def before(self) -> list[str]:
        return [text for kind, text in self.lines if kind in (" ", "-")]

    @property
    def after(self) -> list[str]:
        return [text for kind, text in self.lines if kind in (" ", "+")]


def _reject(message: str, key: str, **context) -> ValidationError:
    return ValidationError(message, message_key=key, context=context or None)


def parse_unified(patch: str) -> list[Hunk]:
    """Parse a unified diff into hunks. Raises ValidationError when malformed."""
    text = (patch or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise _reject("The patch is empty.", "patch.empty")
    raw_lines = text.split("\n")
    if raw_lines and raw_lines[-1] == "":
        # The trailing newline of the patch text is not a line.
        raw_lines.pop()
    hunks: list[Hunk] = []
    index = 0
    while index < len(raw_lines):
        line = raw_lines[index]
        match = _HUNK_RE.match(line)
        if match is None:
            if line.startswith(_STOP_PREFIXES) or not line.strip():
                index += 1
                continue
            raise _reject(
                f"Expected a @@ hunk header, found: {line[:60]!r}",
                "patch.bad_header",
                line=index + 1,
            )
        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) is not None else 1
        new_start = int(match.group(3))
        new_count = int(match.group(4)) if match.group(4) is not None else 1
        header = (match.group(5) or "").strip()
        index += 1
        body: list[tuple[str, str]] = []
        while index < len(raw_lines):
            candidate = raw_lines[index]
            if _HUNK_RE.match(candidate) or candidate.startswith(("--- ", "+++ ")):
                break
            if candidate == "":
                # A truly empty line ends the hunk: a blank *context* line is
                # encoded as a single space in a unified diff, so accepting ""
                # as context would silently add a line that is not in the file.
                break
            marker, payload = candidate[0], candidate[1:]
            if marker not in (" ", "-", "+"):
                raise _reject(
                    f"Unsupported patch line: {candidate[:60]!r}",
                    "patch.bad_line",
                    line=index + 1,
                )
            body.append((marker, payload))
            index += 1
        if not body:
            raise _reject("A hunk has no lines.", "patch.empty_hunk")
        removed = sum(1 for kind, _ in body if kind in (" ", "-"))
        added = sum(1 for kind, _ in body if kind in (" ", "+"))
        if old_count and removed != old_count:
            raise _reject(
                f"Hunk declares {old_count} old lines but carries {removed}.",
                "patch.count_mismatch",
                hunk=len(hunks) + 1,
            )
        if new_count and added != new_count:
            raise _reject(
                f"Hunk declares {new_count} new lines but carries {added}.",
                "patch.count_mismatch",
                hunk=len(hunks) + 1,
            )
        hunks.append(
            Hunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                header=header,
                lines=tuple(body),
            )
        )
    if not hunks:
        raise _reject("The patch contains no @@ hunks.", "patch.no_hunks")
    return hunks


def _find(haystack: list[str], needle: list[str], start: int) -> int:
    if not needle:
        return start
    limit = len(haystack) - len(needle)
    for position in range(max(0, start), limit + 1):
        if haystack[position : position + len(needle)] == needle:
            return position
    return -1


def apply_unified(original: str, patch: str) -> tuple[str, int]:
    """Apply ``patch`` to ``original``; return ``(new_text, hunks_applied)``."""
    hunks = parse_unified(patch)
    trailing_newline = original.endswith("\n") or original == ""
    lines = original.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    cursor = 0
    for number, hunk in enumerate(hunks, start=1):
        before = hunk.before
        after = hunk.after
        if not before:
            raise _reject(
                f"Hunk {number} has no lines to match.",
                "patch.hunk_no_context",
                hunk=number,
            )
        position = _find(lines, before, cursor)
        if position < 0:
            first = next((text for text in before if text.strip()), "")
            raise _reject(
                f"Hunk {number} does not match the file. First expected line: {first[:80]!r}",
                "patch.hunk_not_found",
                hunk=number,
                first_line=first[:120],
            )
        lines[position : position + len(before)] = after
        cursor = position + len(after)
    result = "\n".join(lines)
    if trailing_newline:
        result += "\n"
    return result, len(hunks)


def apply_replace(
    original: str, find: str, replace: str, *, replace_all: bool = False
) -> tuple[str, int]:
    """Replace a literal block. Refuses an ambiguous or absent match."""
    if not find:
        raise _reject("The text to find is empty.", "patch.empty_find")
    normalised = original.replace("\r\n", "\n")
    needle = find.replace("\r\n", "\n")
    haystack = normalised
    if needle.endswith("\n") and not haystack.endswith("\n"):
        # Accept both "line\nline" and "line\nline\n" spellings.
        needle = needle[:-1]
    count = haystack.count(needle)
    if count == 0:
        raise _reject("That text does not appear in the file.", "patch.find_not_found")
    if count > 1 and not replace_all:
        raise _reject(
            f"That text appears {count} times. Add more context or pass replace_all.",
            "patch.find_ambiguous",
            count=count,
        )
    updated = haystack.replace(needle, replace.replace("\r\n", "\n"), -1 if replace_all else 1)
    return updated, count if replace_all else 1
