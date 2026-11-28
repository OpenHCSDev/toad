"""Mobile chrome hairlines, flush NormalInputBox outer margin, suspend animation pause,
and virtual-scroll applicationStateChanged cleanup."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QWidget
from textual.geometry import Spacing

from toad.client.application import ACTIVE_PRESENCE, SUSPENDED_PRESENCE
from toad.client.connection import FailedObservation, NotObserving, Observation, Observing, RemoteCoreConnection
from toad.client.history import ReadMarkedHistory, WirePageBuffer
from toad.preferences import SavedSettings
from toad.qt.side_bar import QtSideBarToggle
from toad.qt.virtual_scroll import RowDocumentStore
from toad.qt.window import QtToadApp
from toad.setting_choices import BottomNavigationBar, NormalInputBox, TopNavigationBar
from toad.sidebar_layout import SidebarLayout
from toad.sidebar_placement import (
    BottomSidebarEdge,
    ChannelsSidebarPlacement,
    LeftSidebarEdge,
    RightSidebarEdge,
    ThreadSidebarPlacement,
    TopSidebarEdge,
)
from toad.terminal_origin import LocalTerminal


def test_normal_input_box_has_no_horizontal_outer_margin():
    assert NormalInputBox.frame_margin == Spacing(0, 0, 0, 0)
    assert NormalInputBox.info_bar_margin(False) == Spacing(0, 1, 0, 1)


def test_navigation_bar_position_declares_content_facing_qt_separator_edge():
    assert TopNavigationBar.qt_separator_edge == "border-bottom"
    assert BottomNavigationBar.qt_separator_edge == "border-top"


def test_sidebar_edge_inner_hairline_and_band_splitters():
    assert BottomSidebarEdge.inner_hairline(100, 30) == (0, 0, 100, 0)
    assert TopSidebarEdge.inner_hairline(100, 30) == (0, 29, 100, 29)
    assert LeftSidebarEdge.inner_hairline(30, 100) == (29, 0, 29, 100)
    assert RightSidebarEdge.inner_hairline(30, 100) == (0, 0, 0, 100)

    layout = SidebarLayout(SavedSettings({}), LocalTerminal)
    layout.move(ChannelsSidebarPlacement, BottomSidebarEdge)
    layout.move(ThreadSidebarPlacement, BottomSidebarEdge)
    first, second = ChannelsSidebarPlacement, ThreadSidebarPlacement

    both_folded = {first: True, second: True}
    assert not layout.splits_before(first, both_folded)
    assert layout.splits_after(first, both_folded)
    assert layout.splits_before(second, both_folded)
    assert not layout.splits_after(second, both_folded)

    first_open = {first: False, second: True}
    assert layout.next_in_band_folded(first, first_open)
    assert not layout.next_in_band_folded(second, first_open)
    both_open = {first: False, second: False}
    assert not layout.next_in_band_folded(first, both_open)


def test_rotated_side_bar_toggle_paints_leading_and_top_hairlines(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.placement = SimpleNamespace(side=BottomSidebarEdge)
    toggle = QtSideBarToggle(host)
    try:
        toggle.resize(24, 120)
        toggle.show_turned("↑", "#comms")
        toggle.set_band_splitters(leading=True, trailing=False)
        pal = toggle.palette()
        mid = pal.color(QPalette.ColorRole.Mid).rgb()
        img = QImage(24, 120, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        toggle._draw_hairlines(painter, vertical=True)
        painter.end()
        assert img.pixelColor(12, 0).rgb() == mid, "Top hairline spans the rotated bottom-band toggle"
        assert img.pixelColor(0, 60).rgb() == mid, "Leading vertical hairline separates rotated toggle from open sibling"
        assert img.pixelColor(23, 60).alpha() == 0, "No trailing hairline when trailing=False"
    finally:
        toggle.deleteLater()
        host.deleteLater()
        app.processEvents()


def test_suspend_pauses_and_resume_restores_animation_timer(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    timer = QTimer()
    fake = MagicMock()
    fake._animation_timer = timer
    fake._animation_interval = None
    fake._animations_paused = False
    fake._schedule_animation = lambda iv: QtToadApp._schedule_animation(fake, iv)
    fake.set_animations_paused = lambda p: QtToadApp.set_animations_paused(fake, p)
    try:
        QtToadApp._schedule_animation(fake, 0.05)
        assert timer.isActive()
        presence = ACTIVE_PRESENCE.suspend(fake)
        assert presence is SUSPENDED_PRESENCE
        assert not timer.isActive()
        presence = presence.activate(fake)
        assert presence is ACTIVE_PRESENCE
        assert timer.isActive()
    finally:
        timer.stop()
        timer.deleteLater()
        app.processEvents()


def test_row_document_store_cleanup_disconnects_app_state(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    class DummyStore(RowDocumentStore):
        def row_key(self, fragment): return fragment
        def row_text(self, fragment): return ""
        def preparation_key_for(self, fragment, font, width): return fragment
        def submit_preparation(self, key, fragment, font, width): pass
        def stop_preparation(self): pass
        def background_qcolor(self): return None
        def final_document_for(self, *args, **kwargs): return None
        def paint_row(self, *args, **kwargs): pass
        def preparation_for(self, *args, **kwargs): return None

    store = DummyStore()
    store.preparer = MagicMock()
    parent = QWidget()
    store._viewport_update_timer.setParent(parent)
    store._measure_timer.setParent(parent)
    store._suspend_release_timer.setParent(parent)
    store.cleanup()
    parent.deleteLater()
    app.processEvents()
    # Must not raise RuntimeError on deleted QTimer after tab cleanup.
    store._application_state_changed(Qt.ApplicationState.ApplicationSuspended)
    store._application_state_changed(Qt.ApplicationState.ApplicationActive)


def test_disconnect_does_not_withdraw_open_channel_view():
    """Temporary disconnects (`FailedObservation`) and startup (`Unobserved`) must not call
    `withdraw_view()` -> `self.view.hide()` on open conversation views; only switching to a
    live observation of a *different* bus root replaces the route."""

    class LiveBus(Observing):
        def __init__(self, root_path: Path):
            self._root = root_path

        @property
        def root(self) -> Path:
            return self._root

        @property
        def core(self):
            return MagicMock()

        def opened_selection(self, access):
            return None

        async def read(self, request):
            return None

        def subscribe_notifications(self, view, build_read):
            return False

        def user_identity(self, project):
            return None

    failed = FailedObservation(ConnectionError("offline"), selection=MagicMock(), access=MagicMock())
    pending = NotObserving(access=MagicMock())
    same_bus = LiveBus(Path("/bus-a"))
    other_bus = LiveBus(Path("/bus-b"))

    assert not failed.replaces("/bus-a")
    assert not pending.replaces("/bus-a")
    assert not same_bus.replaces("/bus-a")
    assert other_bus.replaces("/bus-a")

    withdrawn: list[str] = []

    def run_mark_read(obs: Observation) -> None:
        withdrawn.clear()
        access = SimpleNamespace(
            observation=SimpleNamespace(observed=lambda: obs),
            connection=RemoteCoreConnection.__new__(RemoteCoreConnection),
        )
        buf = WirePageBuffer.__new__(WirePageBuffer)
        buf.scope = SimpleNamespace(closed=False)
        buf.loader = SimpleNamespace(access=access, root=Path("/bus-a"))
        buf.runtime = None

        class DummyHistory(ReadMarkedHistory):
            page_source = buf
            is_attached = True

            async def source_is_current(self, snap):
                return False

            def withdraw_view(self) -> None:
                withdrawn.append("withdrawn")

        history = DummyHistory.__new__(DummyHistory)
        snap = SimpleNamespace(current=lambda h: True)
        asyncio.run(history._mark_read(snap))

    run_mark_read(failed)
    assert withdrawn == [], "Internet disconnect must leave the channel view visible"
    run_mark_read(pending)
    assert withdrawn == [], "Unobserved startup state must leave the channel view visible"
    run_mark_read(other_bus)
    assert withdrawn == ["withdrawn"], "Switching to a different bus root withdraws old tabs"


def test_wire_view_skips_rpc_storm_on_pure_activity_or_read_ticks():
    """Activity heartbeats, read marks, notifications, goal ticks, and expiry ticks must not
    trigger `comms_conversation_revision` / `comms_latest_sequence` / `comms_wire_revision`
    RPCs when bus_seq, bus_changes, history, registry, and catalog did not move."""
    from dataclasses import replace

    from agent_comms.messaging.revision_views import RegistrationsView
    from agent_comms.presentation import WireRevision
    from agent_comms.storage.file_observation import FileIdentity, FileRevision
    from toad.client.history import ConversationRevision, WireView

    base = WireRevision.empty()
    seen = ConversationRevision(stores=base, selection=MagicMock())
    rev = lambda n: FileRevision(FileIdentity(device=1, inode=n), size=10 * n, mtime_ns=n, ctime_ns=n)

    # Pure activity / reads / expiry / notification ticks -> unchanged for wire history & config.
    activity_tick = replace(base, expiry_tick=90, notification_evidence=5,
                            activity=(rev(1),), reads=(rev(2),))
    assert not WireView._conversation_stores_changed(seen, activity_tick)
    assert not activity_tick.changed_since(RegistrationsView(), base)

    # New bus message -> bus_seq advances -> must refresh wire history (not thread config).
    bus_msg = replace(base, bus_seq=1)
    assert WireView._conversation_stores_changed(seen, bus_msg)
    assert not bus_msg.changed_since(RegistrationsView(), base)

    # Registry / catalog change -> must refresh both wire history and thread config.
    reg_change = replace(base, catalog=(rev(3),))
    assert WireView._conversation_stores_changed(seen, reg_change)
    assert reg_change.changed_since(RegistrationsView(), base)


def test_scroll_in_motion_defers_notifications_reads_style_and_decorative_clock():
    """Active scroll motion defers notification WS re-subscriptions, painted read-mark RPCs,
    lazy message_style reads, and infinite decorative chrome animations until settle, without
    duplicate `ReaderWindow` names in either frontend's MRO."""
    from types import SimpleNamespace
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    from agent_comms.messaging.message_reference import MessageReference
    from agent_comms.messaging.read_basis import NoDisplaySelection
    from toad.client.history import ReadMarkedHistory
    from toad.client.history_notifications import OneHistoryNotifications, SourceNotifications
    from toad.client.history_pager import PagingWindow
    from toad.client.history_reads import NothingToRead
    from toad.history_jump import PagedReader
    from toad.qt.history import QtHistoryWindow
    from toad.qt.name_wave import QtSessionTabBar, QtTabWave
    from toad.qt.widget_animation import QtAnimationClock
    from toad.widgets.history_anchor import HistoryWindow

    # No duplicate ReaderWindow name in either frontend MRO (IDEN-2).
    for cls in (QtHistoryWindow, HistoryWindow):
        names = [c.__name__ for c in cls.__mro__]
        assert names.count("ReaderWindow") == 1
        assert issubclass(cls, PagedReader)
        assert issubclass(cls, PagingWindow)

    # Scroll-motion deferral on SourceNotifications + ReadMarkedHistory.
    class _FakeWindow(PagingWindow):
        def __init__(self) -> None:
            self._moving = True

        @property
        def scroll_in_motion(self) -> bool:
            return self._moving

    win = _FakeWindow()
    subscribed: list[tuple] = []
    marked: list[str] = []
    styled: list[str] = []
    scheduled: list[object] = []

    class _FakeHistory(SourceNotifications, ReadMarkedHistory):
        can_draw_on_screen = True
        is_attached = True
        window = win
        notification_references = (MessageReference(seq=1, message_id="1-abc"),)

        def __init__(self, view) -> None:
            self.notification_view = view
            self._painted_reads = {"k": SimpleNamespace(evidence="proof")}
            self._read_mark_scheduled = False
            self.page_source = SimpleNamespace(painted_read=lambda _h: SimpleNamespace(start=lambda _m: marked.append("read")))

        def notification_identity_for(self, _wanted):
            return NoDisplaySelection()

        def read_running(self) -> bool:
            return False

        def call_after_refresh(self, cb, *args) -> None:
            scheduled.append((cb, args))

        def follow_message_style(self) -> None:
            styled.append("style")

    class _FakeView(OneHistoryNotifications):
        def __init__(self) -> None:
            self.app = SimpleNamespace(coordination_access=SimpleNamespace(shows_notifications=lambda _v: False))
            self.message_history = _FakeHistory(self)

        def subscribe_notifications(self, references) -> bool:
            subscribed.append(tuple(references))
            return True

        def report_queue_evidence(self) -> None:
            pass

        def run_notification_work(self, work) -> None:
            pass

        def check_notifications_after_refresh(self) -> None:
            pass

    view = _FakeView()
    hist = view.message_history

    # While scrolling: notifications, read-marks, after-paint schedule, and style lookup all defer.
    view.check_notifications()
    hist.mark_visible_after_paint()
    assert isinstance(hist.read_visible(), NothingToRead)
    assert subscribed == []
    assert marked == []
    assert scheduled == []
    assert styled == []

    # Once scroll settles: notifications, read-marks, and style flush cleanly.
    win._moving = False
    view.check_notifications()
    hist.mark_visible()
    hist.mark_visible_after_paint()
    assert len(subscribed) == 1
    assert marked == ["read"]
    assert len(scheduled) == 1

    # QtAnimationClock pauses decorative chrome targets while scrolling and resumes on settle.
    _app = QApplication.instance() or QApplication([])
    intervals: list[float | None] = []
    clock = QtAnimationClock(intervals.append)
    bar = QtSessionTabBar(clock, QColor("#ff8800"), QColor("#eeeeee"))
    bar.show()
    wave = QtTabWave(bar, "t1")
    wave.start_wave()
    assert wave.animation_visible is True
    assert bar.marquee.animation_visible is True
    owner = object()
    clock.set_scrolling(owner, True)
    assert clock.scrolling is True
    assert wave.animation_visible is False
    assert bar.marquee.animation_visible is False
    assert intervals[-1] is None
    clock.set_scrolling(owner, False)
    assert clock.scrolling is False
    assert wave.animation_visible is True
    assert intervals[-1] is not None
    wave.stop_wave()
    bar.deleteLater()
