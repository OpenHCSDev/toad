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
