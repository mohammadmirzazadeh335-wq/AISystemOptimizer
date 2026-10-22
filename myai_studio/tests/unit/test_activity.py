"""The activity feed translates at render time, not at record time."""

from __future__ import annotations

import pytest

from myai.core.events import SignalBus
from myai.i18n import current_language, set_language
from myai.services.activity import ActivityService


@pytest.fixture(autouse=True)
def _restore_language():  # noqa: ANN202
    original = current_language()
    yield
    set_language(original)


def test_status_key_is_translated_when_the_row_is_drawn() -> None:
    service = ActivityService(SignalBus())
    item = service.record(
        key="agent.activity_run",
        kwargs={"status_key": "agent.status_ok", "tools": 2},
        kind="agent",
    )
    set_language("en")
    assert item.display() == "Agent run: Completed · 2 tool calls"
    set_language("fa")
    assert item.display() == "اجرای عامل: کامل شد · 2 فراخوان ابزار"


def test_plain_text_items_are_untouched() -> None:
    service = ActivityService(SignalBus())
    item = service.record("no key here")
    set_language("fa")
    assert item.display() == "no key here"


def test_unknown_key_does_not_raise() -> None:
    service = ActivityService(SignalBus())
    item = service.record(key="does.not.exist")
    assert item.display()
