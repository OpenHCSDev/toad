"""Both frontends' history windows change what they draw through one shared algorithm; a
window supplies only what its toolkit does differently."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

from toad.client.history_pager import ReaderPlacement
from toad.client.reader_position import FragmentPosition
from toad.history_jump import JumpsToLatest


class Window(ReaderPlacement, JumpsToLatest):
    """A history window with no toolkit: it records what the shared change asks of it."""

    geometry_revision = 0
    is_attached = True

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.screen = SimpleNamespace(is_current=True, reader_kept=lambda window: self.asked.append("reader kept"))

    @asynccontextmanager
    async def tree_change(self):
        self.asked.append("rows held")
        try:
            yield
        finally:
            self.asked.append("rows released")
            self.geometry_revision += 1

    def request_reader_layout(self) -> None:
        self.asked.append("layout")
        self.history_change.finish_layout(self.history_change.layout_requests)

    def place_reader(self) -> bool:
        self.asked.append("reader placed")
        return False


def test_a_change_holds_the_rows_then_waits_for_the_layout_that_puts_the_reader_back():
    window = Window()

    async def change() -> None:
        async with window.preserve_history():
            window.asked.append("pages changed")

    asyncio.run(change())

    assert window.asked == ["rows held", "reader kept", "pages changed", "rows released", "layout", "reader placed"]


def test_both_frontends_windows_inherit_the_change_and_keep_only_their_native_steps():
    from toad.qt.history import QtHistoryWindow
    from toad.widgets.history_anchor import HistoryWindow

    for window in (HistoryWindow, QtHistoryWindow):
        for shared in ("preserve_history", "layout_scroll", "place_reader", "check_follow", "release_anchor",
                       "message_too_tall", "message_head_hidden", "place_layout_reader", "reader_for_layout"):
            assert getattr(window, shared) is getattr(ReaderPlacement, shared), (window, shared)
        assert window.keep_reader is JumpsToLatest.keep_reader, window
        for native in ("tree_change", "request_reader_layout"):
            assert native in vars(window), (window, native)


def test_a_qt_row_under_the_top_edge_names_the_readers_message_and_how_far_into_it():
    from toad.qt.history import QtRowLocation, QtRowUnderTop

    fragment = SimpleNamespace(key="message")
    position = QtRowUnderTop(None, fragment, 0, 400, 30, 120).reader_position(None)

    assert position == FragmentPosition("message", 0.25, 120, block=0)

    # The row was measured again, twice as tall and 500 px further down: the reader is the
    # same quarter into it.
    rect = SimpleNamespace(top=lambda: 500, height=lambda: 240)
    window = SimpleNamespace(scroll_y=1000, row_rect=lambda row: rect)
    assert QtRowLocation(7, fragment).destination(window, position.fraction) == 1000 + 500 + 60


def test_both_frontends_histories_place_an_arrival_through_the_shared_pager():
    from toad.client.history_pager import HistoryPager
    from toad.qt.history import QtConversationHistory
    from toad.widgets.transcript_history import LineHistory

    for history in (LineHistory, QtConversationHistory):
        for shared in ("hold_arrival", "page_holding"):
            assert getattr(history, shared) is getattr(HistoryPager, shared), (history, shared)


def test_a_paused_source_observes_the_scope_its_pager_view_owns():
    """A Qt pager is not a widget and has no Textual ancestor tree to search."""
    from toad.client.history import WirePageBuffer
    from toad.client.history_state import WaitingSourceWork
    from toad.client.prepared_pages import PreparedPageSource
    from toad.core.events import CoordinationObserved
    from toad.transcript_scope import NoTranscript

    observed = []
    saved_subscribed = []
    saved_retired = []

    @contextmanager
    def observe(owner, access, resume):
        observed.append((owner, access, resume))
        yield

    access = SimpleNamespace(events=object())
    view = SimpleNamespace(
        thread_scope=SimpleNamespace(observe=observe),
        observe_core_callback=lambda stream, event_type, cb: (saved_subscribed.append((stream, event_type, cb)), "saved-sub")[1],
        retire_core=lambda sub: saved_retired.append(sub),
    )
    owner = SimpleNamespace(
        view=view,
        page_source=PreparedPageSource(),
        app=SimpleNamespace(coordination_access=access),
    )
    waiting = WaitingSourceWork(owner, object(), lambda: None, object())

    with waiting.observe():
        assert saved_subscribed == [(access.events, CoordinationObserved, waiting.resume)]
        assert saved_retired == []

    assert observed == [(view, access, waiting.resume)]
    assert saved_retired == ["saved-sub"]

    # A wire conversation has NoTranscript as thread_scope and inherits the same
    # PreparedPageSource.observe_availability so both transcript and wire reads wake on
    # CoordinationObserved.
    subscribed = []
    retired = []
    wire_view = SimpleNamespace(
        thread_scope=NoTranscript(),
        observe_core_callback=lambda stream, event_type, cb: (subscribed.append((stream, event_type, cb)), "sub")[1],
        retire_core=lambda sub: retired.append(sub),
    )
    wire_source = object.__new__(WirePageBuffer)
    wire_owner = SimpleNamespace(
        view=wire_view,
        page_source=wire_source,
        app=SimpleNamespace(coordination_access=access),
    )
    wire_waiting = WaitingSourceWork(wire_owner, object(), lambda: None, object())

    with wire_waiting.observe():
        assert subscribed == [(access.events, CoordinationObserved, wire_waiting.resume)]
        assert retired == []

    assert retired == ["sub"]
