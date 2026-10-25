"""Textual-facing: a painted transcript marks the session that holds it visible, even when the last tab closed before the paint landed."""

from types import SimpleNamespace

from toad.app import HeapFrozen, ToadApp
from toad.screens.session_view import SessionView
from toad.transcript_publication import BoundFrame


def test_a_paint_after_the_last_tab_closed_marks_its_own_session():
    marked = []
    painted_session = SimpleNamespace(mark_visible=lambda: marked.append("painted"))
    app = SimpleNamespace(heap=HeapFrozen(), selected_session=None)
    app.history_displayed = lambda: ToadApp.history_displayed(app)
    view = SimpleNamespace(
        app=app,
        query_ancestor=lambda kind: painted_session if kind is SessionView else None,
        settle_user_message=lambda: None,
    )
    owner = SimpleNamespace(displayed_cursor=None)
    frame = BoundFrame(SimpleNamespace(view=view), owner, 0)

    frame.record("cursor")

    assert marked == ["painted"]
    assert owner.displayed_cursor == "cursor"
