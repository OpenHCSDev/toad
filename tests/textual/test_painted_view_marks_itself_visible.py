"""Textual-facing: a painted transcript marks the session that holds it visible, even when the last tab closed before the paint landed, and a hidden tab's paint leaves it unread."""

from types import SimpleNamespace

import pytest

from toad.app import HeapFrozen, ToadApp
from toad.screens.session_view import SessionView
from toad.transcript_publication import BoundFrame


@pytest.mark.parametrize("on_screen, marked", [(True, ["painted"]), (False, [])])
def test_a_paint_after_the_last_tab_closed_marks_only_its_own_session(on_screen, marked):
    seen = []
    session = SimpleNamespace(is_current=on_screen, mark_visible=lambda: seen.append("painted"))
    session.history_painted = lambda: SessionView.history_painted(session)
    app = SimpleNamespace(heap=HeapFrozen(), selected_session=None)
    app.history_displayed = lambda: ToadApp.history_displayed(app)
    view = SimpleNamespace(
        app=app,
        query_ancestor=lambda kind: session if kind is SessionView else None,
        settle_user_message=lambda: None,
    )
    owner = SimpleNamespace(displayed_cursor=None)

    BoundFrame(SimpleNamespace(view=view), owner, 0).record("cursor")

    assert seen == marked
    assert owner.displayed_cursor == "cursor"
