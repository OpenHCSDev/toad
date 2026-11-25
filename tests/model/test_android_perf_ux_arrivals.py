"""Focused tests for Android/Qt perf, mobile UX, resume observation, and unified arrivals."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

from agent_comms.coordination.errors import CoordinationReadUnavailable
from agent_comms.transport.remote_core import ConnectorObserverClosed
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget

from toad.client.history import ObservedViewportRequest, RestyledViewportRequest
from toad.client.history_state import LatestReplacementViewportRequest
from toad.key_modes import Standard, VimInsert
from toad.markdown_links import LinkContext
from toad.preferences import DiffSettings
from toad.qt.history import HistoryRowDelegate, QtJumpBar
from toad.qt.lines import QtLineRenderer
from toad.qt.name_wave import QtSessionTabBar, QtTabWave
from toad.qt.overlay_scrollbar import OverlayScrollBar
from toad.qt.prompt_stack import QtInfoBar
from toad.qt.theme import current_scheme
from toad.qt.widget_animation import QtAnimationClock
from toad.session_observation import GoalObservation, SessionObservation
from toad.sidebar_placement import BottomSidebarEdge, HeightSidebarEdge


def test_session_observation_catches_connector_observer_closed():
    assert issubclass(ConnectorObserverClosed, CoordinationReadUnavailable)
    assert CoordinationReadUnavailable in SessionObservation.errors
    assert CoordinationReadUnavailable in GoalObservation.errors


def test_history_row_delegate_uses_compact_tiles():
    assert HistoryRowDelegate.TILE == 256


def test_horizontal_sidebar_toggle_is_two_rows_with_single_centered_line():
    assert HeightSidebarEdge.collapsed_extent == 2
    assert BottomSidebarEdge.toggle_text(True, "#comms") == "↑  #comms  ↑"
    assert "\n" not in BottomSidebarEdge.toggle_text(True, "all")


def test_replacement_viewport_requests_declare_arrival_animation():
    assert ObservedViewportRequest.animates_arrivals is True
    assert LatestReplacementViewportRequest.animates_arrivals is True
    assert RestyledViewportRequest.animates_arrivals is False


def test_qt_editing_mode_badge_hides_standard_and_collapses_empty_info_bar(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    from toad.markdown_links import ReferenceContext
    import inspect

    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(current_scheme(os.environ), LinkContext(Path("/tmp"), concrete()), DiffSettings())
    scope = MagicMock()
    scope.configuration_state.get_resolved_value.return_value = True
    parent = QWidget()
    bar = QtInfoBar(scope, renderer, parent)
    try:
        bar.badge.present_editing_mode(Standard(), focused=False)
        assert bar.badge.isHidden()
        assert bar.isHidden()

        bar.badge.present_editing_mode(VimInsert(), focused=True)
        assert not bar.badge.isHidden()
        assert bar.badge.text() == VimInsert().label
        assert not bar.isHidden()

        from toad.qt.composer import Receipt
        receipt = Receipt(MagicMock(), renderer, bar)
        assert receipt.isHidden()
    finally:
        parent.deleteLater()


def test_qt_session_tab_bar_caches_shown_title_across_wave_ticks(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    clock = QtAnimationClock(lambda _interval: None)
    scheme = current_scheme(os.environ)
    from PySide6.QtGui import QColor

    bar = QtSessionTabBar(clock, QColor("#ff00ff"), QColor("#ffffff"))
    try:
        bar.show_tabs([("#comms", "comms"), ("toad-qt", "toad")])
        bar.resize(400, 36)
        rect1, text1 = bar._cached_title(0)
        assert text1 == "#comms"
        assert isinstance(rect1, QRect)
        assert len(bar._shown_titles) == 1
        # Repeated read reuses cached tuple without recomputing style option.
        rect2, text2 = bar._cached_title(0)
        assert (rect1, text1) == (rect2, text2)
        # Updating tab text invalidates cache.
        bar.show_tabs([("#comms (3)", "comms"), ("toad-qt", "toad")])
        assert bar._shown_titles == {}
    finally:
        bar.deleteLater()


def test_qt_jump_to_latest_cancels_active_scroller_momentum(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    from PySide6.QtWidgets import QScroller
    from toad.qt.history import QtHistoryWindow

    events: list[str] = []

    class _FakeScroller:
        def state(self):
            return QScroller.State.Scrolling

        def stop(self):
            events.append("scroller.stop")

    fake_scroller = _FakeScroller()
    monkeypatch.setattr(QScroller, "scroller", classmethod(lambda cls, _target: fake_scroller))

    class _FakeHeadReveal:
        def cancel(self):
            events.append("head_reveal.cancel")

    class _FakeWindow:
        head_reveal = _FakeHeadReveal()
        glide = None
        _arrived = ("k1",)
        widget_gone = False
        _flinging = True
        _fling_stopped = True
        _overshoot = -42.0
        _travel_origin = 128.0

        def viewport(self):
            return object()

    win = _FakeWindow()
    QtHistoryWindow._stop_scroll_momentum(win)
    assert events == ["head_reveal.cancel", "scroller.stop"]
    assert win._arrived == ()
    assert win._flinging is False
    assert win._fling_stopped is False
    assert win._overshoot == 0.0
    assert win._travel_origin == 0.0


def test_wire_view_refresh_thread_config_ignores_route_changed_error():
    import asyncio
    from agent_comms.errors import RouteChangedError
    from toad.client.history import WireView

    class _FakeSource:
        async def compose_access(self):
            return MagicMock(read_only=False)

        async def update_mentions(self, _view):
            raise RouteChangedError("Comms service changed before the sidebar was read")

    class _FakeHistory:
        page_source = _FakeSource()

        def source_snapshot(self):
            return object()

        async def source_is_current(self, _snapshot):
            return True

    class _FakeView:
        message_history = _FakeHistory()
        thread_status = ""
        shown = False

        async def thread_label_read(self):
            return None

        async def refresh_composer(self, _compose):
            return None

        def mentions_read(self):
            return None

        def thread_status_shown(self):
            self.shown = True

    view = _FakeView()
    asyncio.run(WireView._refresh_thread_config(view))
    assert view.shown is False


def test_open_band_room_raises_folded_peer_beside_open_bar():
    from textual.geometry import Size
    from toad.preferences import SavedSettings
    from toad.sidebar_layout import SidebarLayout
    from toad.sidebar_placement import (
        BottomSidebarEdge,
        ChannelsSidebarPlacement,
        ThreadSidebarPlacement,
        WidthSidebarEdge,
    )
    from toad.terminal_origin import LocalTerminal

    layout = SidebarLayout(SavedSettings(), LocalTerminal)
    layout.move(ChannelsSidebarPlacement, BottomSidebarEdge)
    layout.move(ThreadSidebarPlacement, BottomSidebarEdge)
    resolved = layout.resolve(
        Size(100, 40),
        {ChannelsSidebarPlacement: False, ThreadSidebarPlacement: True},
    )
    open_bar = resolved.bars[ChannelsSidebarPlacement]
    folded_peer = resolved.bars[ThreadSidebarPlacement]
    assert folded_peer.width == WidthSidebarEdge.collapsed_extent
    assert folded_peer.height == open_bar.height
    assert folded_peer.y == open_bar.y
    assert not open_bar.overlaps(folded_peer)


def test_history_row_delegate_styled_formatting_fast_paths_cached_key():
    from collections import OrderedDict

    class _ExplodingFragment:
        @property
        def clipboard_text(self):
            raise AssertionError("clipboard_text must not be evaluated on a cache hit")

    cached = object()
    delegate = MagicMock()
    delegate._prepared = OrderedDict([("k1", cached)])
    result = HistoryRowDelegate.styled_formatting(delegate, "k1", _ExplodingFragment(), None, 400)
    assert result is cached


def test_composer_fit_height_resets_scroll_when_wrapped_lines_fit(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    from toad.qt.composer import Composer

    vbar = MagicMock()
    editor = MagicMock()
    editor.visual_line_count.return_value = 2
    editor.fontMetrics.return_value.lineSpacing.return_value = 20
    editor.verticalScrollBar.return_value = vbar

    composer = MagicMock()
    composer.editor = editor
    composer.document_margin.return_value = 4
    composer.visible_viewport_height.return_value = 400
    composer.visible_editor_lines.return_value = 2
    composer.editor_height.return_value = 48

    Composer.fit_height(composer)
    vbar.setValue.assert_called_once_with(0)


def test_qt_session_tab_bar_close_button_sits_inside_painted_tab(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QTabBar, QToolButton

    clock = QtAnimationClock(lambda _interval: None)
    bar = QtSessionTabBar(clock, QColor("#ff00ff"), QColor("#ffffff"))
    bar.setTabsClosable(True)
    bar.setExpanding(False)
    bar.setStyleSheet(
        f"QTabBar::tab {{ padding: 6px 10px 6px 12px; margin-right: {bar.TAB_GAP}px; }}"
    )
    closed: list[int] = []
    bar.tabCloseRequested.connect(closed.append)
    try:
        bar.show_tabs([("#comms", "comms"), ("toad-qt", "toad")])
        bar.resize(400, 40)
        bar.show()
        app.processEvents()
        for index in range(bar.count()):
            tab_rect = bar.tabRect(index)
            slot = bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
            assert slot is not None
            btn = slot.findChild(QToolButton)
            assert btn is not None and btn.text() == "×"
            assert btn.width() >= 24 and btn.height() >= 24
            btn_in_bar = btn.geometry().translated(slot.pos())
            assert btn_in_bar.right() <= tab_rect.right() - bar.TAB_GAP
        bar.tabButton(1, QTabBar.ButtonPosition.RightSide).findChild(QToolButton).click()
        assert closed == [1]
    finally:
        bar.deleteLater()


def test_qt_toad_app_apply_safe_area_tracks_keyboard_inset(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    from PySide6.QtCore import QMargins, QRectF
    from PySide6.QtGui import QGuiApplication
    from toad.qt.window import QtToadApp

    fake_ime = MagicMock()
    fake_ime.isVisible.return_value = True
    fake_ime.keyboardRectangle.return_value = QRectF(0, 600, 411, 314)
    monkeypatch.setattr(QGuiApplication, "inputMethod", staticmethod(lambda: fake_ime))

    win = MagicMock()
    win._safe_area_margins = QMargins(0, 42, 0, 24)
    win.rect.return_value = QRect(0, 0, 411, 914)

    QtToadApp._apply_safe_area(win)
    win.setContentsMargins.assert_called_with(0, 42, 0, 314)

    fake_ime.isVisible.return_value = False
    QtToadApp._apply_safe_area(win)
    win.setContentsMargins.assert_called_with(0, 42, 0, 24)


def test_scroll_perf_optimizations_cache_overlays_and_pause_ambient_waves(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    import inspect
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QListView
    from toad.markdown_links import ReferenceContext

    scheduled: list[float | None] = []
    clock = QtAnimationClock(scheduled.append)
    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())

    # 1. QtAnimationClock pauses QtTabWave while a history view scrolls and resumes on Inactive.
    bar = QtSessionTabBar(clock, QColor("#ff00ff"), QColor("#ffffff"))
    bar.show_tabs([("#comms", "comms")])
    bar.show()
    wave = bar.waves.setdefault("comms", QtTabWave(bar, "comms"))
    assert wave.animation_visible is True
    scroller_owner = QWidget()
    clock.set_scrolling(scroller_owner, True)
    assert clock.ambient_paused is True
    assert wave.animation_visible is False
    clock.set_scrolling(scroller_owner, False)
    assert clock.ambient_paused is False
    assert wave.animation_visible is True

    # 2. QtJumpBar caches its rendered pill QPixmap across repeated paints.
    parent = QWidget()
    parent.resize(360, 600)
    parent.show()
    jump = QtJumpBar(parent, renderer)
    jump.resize(jump.sizeHint())
    jump.show()
    jump.grab()
    first_cache = jump._pill_cache
    assert first_cache is not None
    jump.grab()
    assert jump._pill_cache is first_cache

    # 3. OverlayScrollBar paints directly without QGraphicsOpacityEffect.
    area = QListView(parent)
    area.resize(360, 600)
    area.show()
    area.verticalScrollBar().setRange(0, 1000)
    area.verticalScrollBar().setPageStep(200)
    OverlayScrollBar.follow(area, clock, renderer, 6)
    overlay = area.findChild(OverlayScrollBar)
    assert overlay is not None
    assert overlay.graphicsEffect() is None
    overlay.moved(100)
    assert overlay.isVisible() and overlay.handle_opacity == 1.0
    overlay.grab()
    overlay.stop()

    bar.deleteLater()
    scroller_owner.deleteLater()
    parent.deleteLater()
    app.processEvents()
