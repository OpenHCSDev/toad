"""Mobile chrome hairlines, flush NormalInputBox outer margin, suspend animation pause,
and virtual-scroll applicationStateChanged cleanup."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QWidget
from textual.geometry import Spacing

from toad.client.application import ACTIVE_PRESENCE, SUSPENDED_PRESENCE
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
