"""In-process registry of live session checks.

``AuthService`` gives every authenticated context a small guard closure that asks
the database whether its login session is still open.  Asking on *every* service
call would be wasteful, so the answer is cached for a couple of seconds - which
would let a context keep working for that long after it was logged out.

This registry closes that window inside one process: logging out, locking the
screen or resetting a password marks the affected guards dead immediately, and
the cache duration only matters for a *second* process (a second copy of the
program on the same server, a task runner).
"""

from __future__ import annotations

from typing import Any

#: ``(user_id, session_id) -> the mutable state dict shared with the guard``
_STATES: dict[tuple[int | None, int | None], dict[str, Any]] = {}


def register(user_id: int | None, session_id: int | None, state: dict[str, Any]) -> None:
    if session_id is None:
        return
    _STATES[(user_id, session_id)] = state


def forget(session_id: int | None) -> None:
    if session_id is None:
        return
    for key in [key for key in _STATES if key[1] == session_id]:
        _STATES.pop(key, None)


def invalidate_session(session_id: int | None, *, reason: str = "logout") -> int:
    """Mark one session's guard dead; returns how many guards were affected."""
    if session_id is None:
        return 0
    state = _STATES.get(next((key for key in _STATES if key[1] == session_id), (None, None)))
    if state is None:
        return 0
    state["alive"] = False
    state["reason"] = reason
    return 1


def invalidate_user(user_id: int | None, *, reason: str = "password_changed",
                    except_session: int | None = None) -> int:
    affected = 0
    for (owner, session_id), state in list(_STATES.items()):
        if owner != user_id or session_id == except_session:
            continue
        state["alive"] = False
        state["reason"] = reason
        affected += 1
    return affected


def revive_session(session_id: int | None) -> int:
    """Undo :func:`invalidate_session` (used after a successful unlock)."""
    if session_id is None:
        return 0
    for (_, sid), state in _STATES.items():
        if sid == session_id:
            state["alive"] = True
            state["checked_at"] = 0.0
            return 1
    return 0


def live_count() -> int:  # pragma: no cover - diagnostics
    return len(_STATES)
