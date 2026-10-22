"""Keep credentials out of logs, error text and the activity feed.

The app never *tries* to write a key anywhere except the encrypted store, but a
mistake in a message (an exception that quotes a header, a debug log that dumps
a request) must not leak the key into ``logs/`` or a crash report.  This module
is the last line of defence: it is cheap, pure and tested, and every log handler
runs it.

The point is not to be clever about every key format; it is that the common
shapes used by this product (OpenRouter, GitHub) can never survive a log call.
"""

from __future__ import annotations

import re

#: Show only this much of a secret when it genuinely must be identified.
VISIBLE_PREFIX = 7
VISIBLE_SUFFIX = 4

_PATTERNS = (
    # OpenRouter / OpenAI style keys, with or without the v1 segment.
    re.compile(r"\bsk-or-v1-[A-Za-z0-9_\-]{4,}"),
    re.compile(r"\bsk-or-[A-Za-z0-9_\-]{4,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    # GitHub tokens and fine-grained tokens.
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    # The generic "Authorization: Bearer …" shape.
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{8,}"),
)


def mask_secret(value: str) -> str:
    """A display form that identifies a key without revealing it."""
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= VISIBLE_PREFIX + VISIBLE_SUFFIX:
        return "*" * len(text)
    return f"{text[:VISIBLE_PREFIX]}…{text[-VISIBLE_SUFFIX:]}"


def redact(text: str) -> str:
    """Replace every credential-looking token in ``text`` with a masked form."""
    if not text or not isinstance(text, str):
        return text
    out = text
    for pattern in _PATTERNS:
        if pattern.groups:
            out = pattern.sub(lambda match: match.group(1) + mask_secret(match.group(2)), out)
        else:
            out = pattern.sub(lambda match: mask_secret(match.group(0)), out)
    return out


def contains_secret(text: str, secrets: list[str]) -> bool:
    """True when any of ``secrets`` appears verbatim (used by the tests)."""
    if not text:
        return False
    return any(secret and secret in text for secret in secrets)
