"""Platform rules that keep the app correct on Windows 11.

Everything that differs between Windows and POSIX lives here so the rest of the
code base stays readable and so the Windows *rules* can be tested from a Linux
runner (they are pure functions, not ``if os.name`` branches hidden in views).

Three things matter for this product:

* child processes must not flash a console window on Windows,
* process output is not always UTF-8 (compilers on Windows often emit the
  console code page), so decoding must never raise,
* Windows silently rewrites file names (trailing dots/spaces, reserved device
  names, characters such as ``:``); a path that looks harmless in the UI can
  then point somewhere else on disk.  Those names are refused up front on
  **every** platform so a project behaves identically after a copy to Windows.
"""

from __future__ import annotations

import codecs
import locale
import os
import re
import subprocess
import sys

IS_WINDOWS = os.name == "nt"
IS_FROZEN = bool(getattr(sys, "frozen", False))

#: Device names Windows reserves in every directory (``NUL.txt`` too).
RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

#: Characters Windows cannot store in a file name.
INVALID_CHARS = frozenset('<>:"|?*')

#: CreateProcess refuses command lines longer than this on Windows.
MAX_PATH = 259

_BAD_CHARS_RE = re.compile(r"[<>\":|?*\x00-\x1f]")


def creation_flags() -> int:
    """Flags for :class:`subprocess.Popen` that hide the child console.

    ``CREATE_NO_WINDOW`` only exists on Windows; on every other platform the
    result is ``0`` so the same call sites work unchanged.
    """
    if not IS_WINDOWS:
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))


def decode_output(data: bytes) -> str:
    """Decode child-process output without ever raising.

    Order matters: UTF-8 first (the app forces ``PYTHONIOENCODING`` and most
    modern toolchains emit UTF-8), then the console code page Windows would
    have used, then Latin-1 as a lossless last resort.
    """
    if not data:
        return ""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", "replace")
    candidates = ["utf-8-sig"]
    try:
        preferred = locale.getpreferredencoding(False)
    except (LookupError, ValueError):  # pragma: no cover - broken locale
        preferred = ""
    for encoding in (preferred, "cp1252", "cp850", "latin-1"):
        if encoding and encoding not in candidates:
            candidates.append(encoding)
    for encoding in candidates:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def filename_problem(name: str) -> str | None:
    """Return a reason code when ``name`` is unsafe as a file/folder name.

    The check is deliberately platform-independent: a project created on Linux
    must still open on Windows.  Reasons are stable codes the UI translates.
    """
    if not name or not name.strip():
        return "empty"
    if name in {".", ".."}:
        return "relative"
    if any(ch in INVALID_CHARS for ch in name) or _BAD_CHARS_RE.search(name):
        return "invalid_chars"
    if name != name.rstrip(" ."):
        return "trailing"
    stem = name.split(".", 1)[0].strip().lower()
    if stem in RESERVED_NAMES:
        return "reserved"
    if len(name) > 120:
        return "too_long"
    return None


def path_problem(parts: list[str] | tuple[str, ...], *, base_length: int = 0) -> str | None:
    """Validate every component of a relative path, then its total length."""
    for part in parts:
        if part in {"", "."}:
            continue
        reason = filename_problem(part)
        if reason is not None:
            return reason
    relative = "/".join(part for part in parts if part not in {"", "."})
    if base_length + len(relative) + 1 > MAX_PATH:
        return "path_too_long"
    return None


def open_command(path: str) -> list[str]:
    """The argv that opens ``path`` in the user's default application."""
    if IS_WINDOWS:  # pragma: no cover - Windows only
        return ["cmd", "/c", "start", "", path]
    if sys.platform == "darwin":  # pragma: no cover - macOS only
        return ["open", path]
    return ["xdg-open", path]
