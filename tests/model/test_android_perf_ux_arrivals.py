"""Focused tests for Android/Qt perf, mobile UX, resume observation, and unified arrivals."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent_comms.coordination.errors import CoordinationReadUnavailable
from agent_comms.transport.remote_core import ConnectorObserverClosed
from PySide6.QtCore import QRect
from PySide6.QtGui import QBrush, QColor, QTextDocument
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem, QWidget

from toad.client.fragments import WireMessage
from toad.client.history import ObservedViewportRequest, RestyledViewportRequest
from toad.client.history_state import LatestReplacementViewportRequest
from toad.key_modes import Standard, VimInsert
from toad.markdown_links import LinkContext
from toad.preferences import DiffSettings
from toad.qt.history import HistoryRowDelegate, QtHistoryWindow, QtJumpBar, RowPictures
from toad.qt.lines import QtLineRenderer
from toad.qt.name_wave import QtSessionTabBar, QtTabWave
from toad.qt.overlay_scrollbar import OverlayScrollBar
from toad.qt.prompt_stack import QtInfoBar
from toad.qt.theme import current_scheme
from toad.qt.virtual_scroll import VirtualRowCanvas
from toad.qt.window import ConversationRows, SidebarItem
from ui_theme.clock import AnimationClock
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
    finally:
        parent.deleteLater()


def test_qt_session_tab_bar_caches_shown_title_across_wave_ticks(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    clock = AnimationClock(lambda _interval: None)
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

    from toad.arrivals import AnimatesArrivals

    class _FakeWindow(AnimatesArrivals):
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
    editor.setFixedHeight.assert_called_once_with(48)
    vbar.setValue.assert_called_once_with(0)


def test_qt_session_tab_bar_close_button_sits_inside_painted_tab(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QTabBar, QToolButton

    clock = AnimationClock(lambda _interval: None)
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


def test_android_ime_window_insets_and_jump_bar_multiline_size_hint(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    import inspect
    from PySide6.QtGui import QFontMetrics
    from toad.markdown_links import ReferenceContext

    # 1. ToadActivity folds Android 11+/15 WindowInsets.Type.ime().bottom into systemBars() via
    #    WindowInsets.Builder (without resizing android.R.id.content / SurfaceView, which flashed
    #    white) and paints the activity window/decor black.
    activity = (Path(__file__).resolve().parents[2]
                / "tools/android/keepalive/java/org/toadcomms/ToadActivity.java").read_text()
    assert "WindowInsets.Type.ime()" in activity
    assert "android.R.id.content" in activity
    assert "WindowInsets.Builder(insets)" in activity
    assert "Color.BLACK" in activity
    assert "view.setPadding" not in activity

    # 2. QtJumpBar.sizeHint measures its multiline text ("Back to bottom\n↓ Esc ↓") by widest
    #    line instead of concatenating both lines with horizontalAdvance.
    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())
    parent = QWidget()
    try:
        jump = QtJumpBar(parent, renderer)
        hint = jump.sizeHint()
        metrics = QFontMetrics(jump.font())
        lines = jump.text().splitlines()
        widest = max(metrics.horizontalAdvance(line) for line in lines)
        concatenated = metrics.horizontalAdvance(jump.text())
        assert len(lines) >= 2
        assert hint.width() < concatenated + 24
        assert hint.width() >= widest + 16
        assert hint.height() >= metrics.size(0, jump.text()).height() + 6
    finally:
        parent.deleteLater()

    # 3. ConversationRows caches char_width, skips height-only resizeEvent refits, and
    #    ConversationRow.wave_visible returns False for collapsed/hidden rows.
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    from toad.qt.window import ConversationRow, ConversationRows
    tree = ConversationRows.__new__(ConversationRows)
    from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
    QTreeWidget.__init__(tree)
    tree.resize(300, 400)
    tree.show()
    try:
        assert tree.char_width() >= 1
        assert tree._cached_char_width is not None
        item = QTreeWidgetItem(tree, ["row"])
        fit_calls = 0
        def fake_fit():
            nonlocal fit_calls
            fit_calls += 1
        item.subtree = lambda: (item,)
        item.fit = fake_fit
        # Height-only resize must not refit rows.
        tree.resizeEvent(QResizeEvent(QSize(300, 220), QSize(300, 400)))
        assert fit_calls == 0
        # Width change refits rows.
        tree.resizeEvent(QResizeEvent(QSize(280, 220), QSize(300, 220)))
        assert fit_calls == 1
        # Collapsed child item is not wave-visible.
        child = ConversationRow.__new__(ConversationRow)
        QTreeWidgetItem.__init__(child, item, ["child"])
        item.setExpanded(False)
        assert child.wave_visible() is False
    finally:
        tree.deleteLater()


def test_scroll_perf_optimizations_cache_overlays_and_keep_animations_live(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    import inspect
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QListView
    from toad.markdown_links import ReferenceContext
    from toad.qt.activity import ActivitySweep

    scheduled: list[float | None] = []
    clock = AnimationClock(scheduled.append)
    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())

    # 1. Ambient animations (tab waves and ActivitySweep loading spinner) stay live and are never
    #    paused while scrolling.
    bar = QtSessionTabBar(clock, QColor("#ff00ff"), QColor("#ffffff"))
    bar.show_tabs([("#comms", "comms")])
    bar.show()
    wave = bar.waves.setdefault("comms", QtTabWave(bar, "comms"))
    assert wave.animation_visible is True
    sweep = ActivitySweep(renderer, clock)
    sweep.show()
    assert sweep.animation_visible is True
    sweep.deleteLater()

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

    # 3. OverlayScrollBar paints directly without QGraphicsOpacityEffect and sits in the right
    #    viewport margin so it never overlaps the viewport (keeping VirtualRowView blit intact).
    area = QListView(parent)
    area.resize(360, 600)
    area.show()
    OverlayScrollBar.follow(area, clock, renderer, 6)
    area.verticalScrollBar().setRange(0, 1000)
    area.verticalScrollBar().setPageStep(200)
    overlay = area.findChild(OverlayScrollBar)
    assert overlay is not None
    assert overlay.graphicsEffect() is None
    assert area.viewportMargins().right() == 6
    assert not overlay.geometry().intersects(area.viewport().geometry())
    overlay.moved(100)
    assert overlay.isVisible() and overlay.handle_opacity == 1.0
    overlay.grab()
    overlay.stop()

    bar.deleteLater()
    parent.deleteLater()
    app.processEvents()


def test_failed_observation_notifications_do_not_crash_on_resume() -> None:
    """Backgrounding Android drops the WebSocket to `FailedObservation`; a `prepare_viewport`
    notification check arriving before reconnect reports the failure once instead of raising
    `ConnectorObserverClosed` out of `self.app.source().core`."""
    from types import SimpleNamespace
    from agent_comms.messaging.message_reference import MessageReference
    from agent_comms.messaging.read_basis import NoDisplaySelection
    from toad.client.connection import ClosedObservation, FailedObservation
    from toad.client.history_notifications import OneHistoryNotifications

    class FakeHistory:
        can_draw_on_screen = True
        notification_references = (MessageReference(seq=1, message_id="1-abc"),)

        def notification_identity_for(self, wanted):
            return NoDisplaySelection()

    class FakeView(OneHistoryNotifications):
        def __init__(self, access):
            self.app = SimpleNamespace(coordination_access=access)
            self.message_history = FakeHistory()
            self.failures: list[Exception] = []

        def report_queue_evidence(self) -> None:
            pass

        def run_notification_work(self, work) -> None:
            pass

        def check_notifications_after_refresh(self) -> None:
            pass

        def notifications_failed(self, failure: Exception) -> None:
            self.failures.append(failure)

    error = RuntimeError("ConnectorObserverClosed: remote stream ended")
    access = SimpleNamespace(shows_notifications=lambda _view: False)
    failed = FailedObservation(error=error, selection=SimpleNamespace(), access=access)
    access.observation = failed
    view = FakeView(access)

    view.check_notifications()
    assert view.failures == [error]
    # Repeated viewport checks while still disconnected do not spam notifications_failed.
    view.check_notifications()
    assert view.failures == [error]

    # ClosedObservation silently ignores notification checks during shutdown.
    access.observation = ClosedObservation(access=access)
    view.check_notifications()
    assert view.failures == [error]


def test_bottom_chrome_yields_to_keyboard_while_open_sidebars_stay() -> None:
    """Bottom-docked navigation and collapsed bottom sidebar toggle strips yield to the soft
    keyboard so the composer sits flush above the keyboard; open bottom sidebars (e.g.
    searching channels) and non-bottom edges stay visible."""
    from types import SimpleNamespace
    import inspect
    from PySide6.QtWidgets import QWidget
    from toad.markdown_links import ReferenceContext
    from toad.preferences import SavedSettings
    from toad.qt.side_bar import QtSideBar, QtWorkspaceChrome
    from toad.setting_choices import BottomNavigationBar, TopNavigationBar
    from toad.sidebar_layout import SidebarLayout
    from toad.sidebar_placement import (
        BottomSidebarEdge,
        ChannelsSidebarPlacement,
        LeftSidebarEdge,
        ThreadSidebarPlacement,
        TopSidebarEdge,
    )
    from toad.terminal_origin import LocalTerminal

    assert BottomNavigationBar.yields_to_keyboard is True
    assert TopNavigationBar.yields_to_keyboard is False
    assert BottomSidebarEdge.yields_to_keyboard is True
    assert TopSidebarEdge.yields_to_keyboard is False
    assert LeftSidebarEdge.yields_to_keyboard is False

    app = QApplication.instance() or QApplication([])
    clock = AnimationClock(lambda _interval: None)
    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())
    parent = QWidget()
    parent.resize(360, 720)
    pages = QWidget(parent)
    layout = SidebarLayout(SavedSettings(), LocalTerminal)
    layout.move(ChannelsSidebarPlacement, BottomSidebarEdge)
    layout.move(ThreadSidebarPlacement, BottomSidebarEdge)
    layout.set_collapsed(ChannelsSidebarPlacement, True)
    layout.set_collapsed(ThreadSidebarPlacement, False)
    chrome = QtWorkspaceChrome(layout, pages, clock=clock, available=lambda _id: True, parent=parent)
    client = SimpleNamespace(
        settings=SimpleNamespace(sidebar=SimpleNamespace(toggle_hint=False)),
        renderer=renderer,
    )
    channels = QtSideBar(layout, ChannelsSidebarPlacement, QWidget(), heading=lambda: "all",
                         laid_out=lambda: None, client=client, parent=chrome)
    thread = QtSideBar(layout, ThreadSidebarPlacement, QWidget(), heading=lambda: "#comms",
                       laid_out=lambda: None, client=client, parent=chrome)
    chrome.sidebars = (channels, thread)

    assert chrome.presented_sidebars() == (channels, thread)
    chrome.set_keyboard_open(True)
    # Collapsed bottom strip hides; open bottom sidebar stays visible.
    assert chrome.presented_sidebars() == (thread,)
    chrome.set_keyboard_open(False)
    assert chrome.presented_sidebars() == (channels, thread)

    parent.deleteLater()
    app.processEvents()


def test_scroll_paint_event_clips_offscreen_tiles_and_tiles_horizontally(monkeypatch) -> None:
    """`VirtualRowCanvas.paintEvent` passes `event.region()` directly into
    `HistoryRowDelegate.paint_pictures` so only visible tiles vertically and horizontally
    are rasterized instead of blowing the 64 MB `RowPictures` cache."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    import inspect
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QFont, QPainter, QPixmap, QRegion, QTextDocument
    from toad.markdown_links import ReferenceContext
    from toad.qt.history import HistoryRowDelegate, RowPictures

    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())
    pictures = RowPictures(64 * 1024 * 1024)
    delegate = HistoryRowDelegate(renderer, pictures, MagicMock())

    # Tall (2560 px) + wide (1800 px) row painted into a 400x300 viewport with clip region.
    doc = QTextDocument()
    doc.setPlainText("line\n" * 120)
    delegate.final_document_for = lambda _frag, _font, _w: doc

    surface = QPixmap(400, 300)
    painter = QPainter(surface)
    assert painter.hasClipping() is False
    rect = QRect(0, -1000, 1800, 2560)
    clip_region = QRegion(QRect(0, 0, 400, 300))
    fake_frag = MagicMock(key="row-1", has_blocks=True, clipboard_text="line")

    # Track tiles rasterized.
    painted_tiles: list[tuple[int, int, int, int]] = []
    orig_paint = delegate._paint_tile_document

    def record_paint(drawing, palette, document, left, top, width, height):
        painted_tiles.append((left, top, width, height))
        orig_paint(drawing, palette, document, left, top, width, height)

    delegate._paint_tile_document = record_paint
    try:
        assert delegate.paint_pictures(painter, fake_frag, rect, clip_region) is True
    finally:
        painter.end()

    # Viewport [0..300] maps to row-local y in [1000..1300] (tiles 3, 4, 5) and x in [0..400] (tile_x 0 only).
    assert painted_tiles, "visible tiles should be rasterized"
    assert len(painted_tiles) <= 3, f"expected <=3 visible tiles, got {len(painted_tiles)}: {painted_tiles}"
    assert all(left == 0 and width == delegate.TILE_X for left, _top, width, _h in painted_tiles)
    assert all(top >= 768 and top <= 1280 for _l, top, _w, _h in painted_tiles)

    # Fractional font sizes produce distinct `drawn_key` entries.
    f1, f2 = QFont("monospace"), QFont("monospace")
    f1.setPointSizeF(10.0)
    f2.setPointSizeF(10.5)
    assert delegate.drawn_key(("k",), f1, 400) != delegate.drawn_key(("k",), f2, 400)
    app.processEvents()


def test_inline_spans_isolates_unmatched_backticks_and_rejects_dotdot_ranges() -> None:
    """An unmatched backtick on one line must never invert subsequent lines into `code_inline`
    (which collapses newlines and eats spaces), and numeric ranges like `row[4..5]` must not
    match `_PATH_PATTERN` as clickable files."""
    from agent_comms.messaging.display_references import ProjectReferences
    from toad.client.line_blocks import CodeRole, TextRole
    from toad.inline_spans import inline_spans
    from toad.markdown_links import _PATH_PATTERN

    context = LinkContext(Path("."), ProjectReferences())
    body = (
        "1. Line with stray `backtick and `KNOBS` cleanly.\n"
        "### 2. Next heading should stay normal prose\n"
        "It spammed `grep` because `sft_v4` had only `3` examples in row[4..5] and row[2..3]."
    )
    spans = inline_spans(body, context)
    rendered = "".join(span.text for span in spans)
    assert "### 2. Next heading should stay normal prose" in rendered
    assert "It spammed grep because sft_v4 had only 3 examples" in rendered
    # Line 3's prose is TextRole, and its backticked tokens are CodeRole (not inverted).
    assert any(span.text == "grep" and span.role is CodeRole for span in spans)
    assert any(span.text == "sft_v4" and span.role is CodeRole for span in spans)
    assert any("It spammed " in span.text and span.role is TextRole for span in spans)

    # `4..5` and `2..3` must not match as bare filenames; real filenames still match.
    assert [m.group("path") for m in _PATH_PATTERN.finditer("row[4..5] and row[2..3]")] == []
    assert [m.group("path") for m in _PATH_PATTERN.finditer("see src/foo.py and archive.tar.gz")] == [
        "src/foo.py", "archive.tar.gz"
    ]


def test_composer_docked_buttons_and_nav_separators_and_ime_inset_file(monkeypatch, tmp_path) -> None:
    """Docked composer buttons sit in `button_row` beside `self.editor` (so typing/backspacing
    never bounces height or adds a fake blank line), `_NavSeparator` draws a 1 px divider, and
    `QtToadApp.fit_safe_area` honors `TOAD_IME_INSET_FILE` across stale `QtWindow.onLayoutChange` reads."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from PySide6.QtCore import QMargins
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QPlainTextEdit, QPushButton
    from toad.qt.composer import Composer
    from toad.qt.window import QtToadApp

    # 1. Docked box buttons sit in `button_row` (with leading stretch) inside `button_box`
    #    under `self.editor` (Attach before Send, right-aligned, full width for text above).
    frame = QFrame()
    frame.resize(300, 80)
    layout = QHBoxLayout(frame)
    editor = QPlainTextEdit(frame)
    editor.resize(200, 40)
    layout.addWidget(editor, 1)
    button_box = QWidget(frame)
    button_row = QHBoxLayout(button_box)
    button_row.addStretch(1)
    layout.addWidget(button_box, 0)

    send_btn = QPushButton("➤")
    attach_btn = QPushButton("+")
    composer = MagicMock(spec=Composer)
    composer.frame = frame
    composer.editor_row = layout
    composer.button_box = button_box
    composer.button_row = button_row
    composer.editor = editor
    composer.box_buttons = ()
    composer.font.return_value = frame.font()
    composer.fontMetrics.return_value = frame.fontMetrics()
    composer.document_margin.return_value = 4
    composer.fit_buttons = lambda: Composer.fit_buttons(composer)
    composer.fit_height = lambda: None

    Composer.add_box_button(composer, send_btn)
    Composer.add_box_button(composer, attach_btn)
    assert composer.box_buttons == (attach_btn, send_btn)
    assert button_row.indexOf(attach_btn) == 1
    assert button_row.indexOf(send_btn) == 2
    assert send_btn.parentWidget() is button_box and attach_btn.parentWidget() is button_box

    # 2. Navigation bar separator helper returns a 1 px QFrame styled via #toad-nav-separator.
    sep = QtToadApp._nav_separator(frame)
    sep.resize(1, 32)
    assert sep.objectName() == "toad-nav-separator"
    assert sep.width() == 1

    # 3. QtToadApp.fit_safe_area protects IME bottom margin against stale getRootWindowInsets().
    inset_file = tmp_path / "ime_bottom_px"
    inset_file.write_text("900", encoding="ascii")
    monkeypatch.setenv("TOAD_IME_INSET_FILE", str(inset_file))

    fake_app = MagicMock()
    fake_app._rest_bottom_margin = 24
    fake_app._keyboard_open = False
    fake_app.KEYBOARD_MARGIN_THRESHOLD = QtToadApp.KEYBOARD_MARGIN_THRESHOLD
    fake_app.devicePixelRatioF.return_value = 3.0
    fake_app._android_ime_bottom_dp = lambda: QtToadApp._android_ime_bottom_dp(fake_app)

    # Stale 24 dp margin from QtWindow.onLayoutChange while keyboard (900 px = 300 dp) is up:
    QtToadApp.fit_safe_area(fake_app, QMargins(0, 48, 0, 24))
    applied = fake_app.setContentsMargins.call_args[0][0]
    assert applied.bottom() == 300
    assert fake_app._keyboard_open is True

    # Keyboard closes -> ToadActivity writes "0" -> resting 24 dp restored cleanly.
    inset_file.write_text("0", encoding="ascii")
    QtToadApp.fit_safe_area(fake_app, QMargins(0, 48, 0, 24))
    applied = fake_app.setContentsMargins.call_args[0][0]
    assert applied.bottom() == 24
    assert fake_app._keyboard_open is False

    # ToadActivity.java wires TOAD_IME_INSET_FILE.
    activity = (Path(__file__).resolve().parents[2]
                / "tools/android/keepalive/java/org/toadcomms/ToadActivity.java").read_text()
    assert "TOAD_IME_INSET_FILE" in activity

    frame.deleteLater()
    sep.deleteLater()
    app.processEvents()


def test_message_font_scale_zoom_and_collapsible_thinking_and_messages(monkeypatch) -> None:
    """Message zoom setting + actions work within [50, 200], thinking blocks default collapsed
    with tappable preview across split parts, and bus messages collapse/expand via header."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    from dataclasses import replace
    from agent_comms.messaging.messages import InfoKind, Message
    from agent_comms.transcript.transcript_events import IncomingTranscript, ThinkingTranscript
    from toad.client.application_actions import ResetZoomAction, TextSizeAction, ZoomInAction, ZoomOutAction
    from toad.client.fragments import FragmentCollapse, FragmentDetails, MessageShown
    from toad.client.line_blocks import Divider, Summary
    from toad.client.message_file_links import NO_PAGE_FILES
    from toad.client.transcript_fragments import RenderBudget, transcript_fragments
    from toad.preferences import SETTINGS, SavedSettings
    from toad.qt.transcript_fragments import QT_FRAGMENT_CLASSES, QtThinkingTranscriptFragment
    from toad.widgets.transcript_fragments import TEXTUAL_FRAGMENT_CLASSES

    # 1. Font scale preference + single nested menu entry (flat zoom actions are shortcut-only).
    saved = SavedSettings()
    assert saved.current.ui.message_font_scale == 100
    saved.set(SETTINGS.ui.message_font_scale, 85)
    assert saved.current.ui.message_font_scale == 85
    assert TextSizeAction.show is True and TextSizeAction.summary()
    for action_cls in (ZoomInAction, ZoomOutAction, ResetZoomAction):
        assert action_cls.show is False
        assert action_cls.summary()

    # 1b. Multi-line Divider renders one centered full-width table per row so shorter rows
    #     have rules extending to both sides cleanly.
    import inspect
    from toad.client.line_blocks import Span, UserRole
    from toad.markdown_links import ReferenceContext
    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings()).at_width(24)
    divider_html = renderer.divider(Divider(
        (Span("▼ pm-trainer-f <── pm-neuro-arch", UserRole),), UserRole,
    ))
    assert divider_html.count("<table ") >= 2
    assert 'align="center"' in divider_html

    # 2. ThinkingTranscriptFragment defaults collapsed and expands across split parts in both frontends.
    long_thought = "\n\n".join(f"Step {i}: " + "analysis " * 30 for i in range(6))
    assert len(long_thought) > RenderBudget().characters
    for classes in (QT_FRAGMENT_CLASSES, TEXTUAL_FRAGMENT_CLASSES):
        built = transcript_fragments(
            (ThinkingTranscript(long_thought, position=1, timestamp=0.0, ordinal=0),),
            resolve_sent=lambda _r: {},
            classes=classes,
            files=NO_PAGE_FILES,
        )
        assert len(built) > 1
        assert built[0].has_details is True
        head_blocks = built[0].line_blocks
        toggle = head_blocks[-1]
        assert isinstance(toggle, Summary)
        assert toggle.spans[0].text.startswith("▶ Thinking")
        assert isinstance(toggle.spans[0].link, FragmentDetails)
        assert all(part.line_blocks == () for part in built[1:])

        # Expanding all parts shows ▼ Thinking + body across parts.
        for part in built:
            part.request_show(part.shown.toggled())
        expanded_head = built[0].line_blocks
        assert len(expanded_head) > len(head_blocks)
        assert any(isinstance(b, Summary) and b.spans[0].text.startswith("▼ Thinking") for b in expanded_head)
        assert all(len(part.line_blocks) >= 1 for part in built[1:])
    assert issubclass(QT_FRAGMENT_CLASSES.thinking, QtThinkingTranscriptFragment)

    # 3. Bus messages carry a clickable ▼/▶ header disclosure and collapse/expand cleanly.
    long_body = "\n\n".join(f"Paragraph {i}: " + "content " * 35 for i in range(6))
    msg = Message(sender="toad-qt", target="#comms", body=long_body, type=InfoKind)
    parts = transcript_fragments(
        (IncomingTranscript.of(msg, reader="tristan"),),
        resolve_sent=lambda _r: {},
        classes=QT_FRAGMENT_CLASSES,
        files=NO_PAGE_FILES,
    )
    assert len(parts) > 1
    head_divider = next(b for b in parts[0].line_blocks if isinstance(b, Divider))
    assert head_divider.spans[0].text == "▼ "
    assert isinstance(head_divider.spans[0].link, FragmentCollapse)

    # Collapse all parts of the message.
    for part in parts:
        part.request_show(replace(part.shown, collapsed=True))
    collapsed_blocks = parts[0].line_blocks
    collapsed_divider = next(b for b in collapsed_blocks if isinstance(b, Divider))
    assert collapsed_divider.spans[0].text == "▶ "
    assert any(isinstance(b, Summary) and isinstance(b.spans[0].link, FragmentCollapse) for b in collapsed_blocks)
    assert all(part.line_blocks == () for part in parts[1:])


def test_span_columns_wraps_only_between_whole_receipt_cells(monkeypatch) -> None:
    """`QtLineRenderer.span_columns` keeps every `name: status` receipt cell unbroken and
    wraps flush-left only between cells (never splitting `pm-trainer: Read` from `20:18`)."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    import inspect
    from PySide6.QtGui import QTextDocument
    from toad.client.line_blocks import MutedRole, NameRole, OpenTarget, Span, SpanColumns
    from toad.markdown_links import ReferenceContext

    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())

    pairs = (
        ("pm-eval-loop", ": Read 20:18"),
        ("pm-trainer", ": Read 20:18"),
        ("pm-trainer-f", ": Read 20:18"),
        ("agy-model", ": Sent"),
        ("pm-pbt", ": Sent"),
        ("pm-trainer-c", ": Sent"),
    )
    block = SpanColumns(tuple((Span(name, NameRole, OpenTarget(name)), Span(status, MutedRole))
                              for name, status in pairs), indent=2)
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setTextWidth(260)
    doc.setHtml(renderer.html((block,)))
    _ = doc.size()

    lines: list[str] = []
    text_block = doc.begin()
    while text_block.isValid():
        layout = text_block.layout()
        for idx in range(layout.lineCount()):
            line = layout.lineAt(idx)
            lines.append(text_block.text()[line.textStart():line.textStart() + line.textLength()].strip())
        text_block = text_block.next()

    assert len(lines) >= 2, "must wrap across multiple lines at phone width"
    # Every `name: status` pair appears intact on a single visual line.
    for name, status in pairs:
        expected = (name + status).replace(" ", "\u00a0").replace("-", "\u2011")
        assert any(expected in line for line in lines), f"{expected!r} split across lines: {lines}"
        assert all(not line.startswith("\u00a0") for line in lines)


def test_parallel_render_and_hold_touch_link_priority_and_text_tap_inversion(monkeypatch, tmp_path) -> None:
    """Covers parallel 2-worker `HoldsRows.render_and_hold`, header name tap priority over
    collapse within touch slop, live text-color inversion via `TapHighlight`, tappable pinned
    sticky header preserving the `▼`/`▶` disclosure arrow, and IME Back-close resync."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    import asyncio
    import inspect
    from PySide6.QtCore import QMargins, QPoint, QRect, Qt
    from PySide6.QtGui import QColor, QTextDocument
    from agent_comms.messaging.messages import InfoKind, Message
    from agent_comms.transcript.transcript_events import IncomingTranscript
    from toad.client.fragments import FragmentCollapse
    from toad.client.line_blocks import OpenTarget
    from toad.client.message_file_links import NO_PAGE_FILES
    from toad.client.prepared_pages import HoldsRows
    from toad.client.transcript_fragments import transcript_fragments
    from toad.markdown_links import ReferenceContext
    from toad.qt.history import QtHistoryWindow, QtStickyHeader
    from toad.qt.transcript_fragments import QT_FRAGMENT_CLASSES
    from toad.qt.virtual_scroll import (
        NO_TAP_HIGHLIGHT,
        PinnedHeaderTapHighlight,
        PinnedLinkTapHighlight,
        RowHeaderTapHighlight,
        RowLinkTapHighlight,
    )
    from toad.qt.window import QtToadApp

    # 1. HoldsRows.render_and_hold dispatches up to two batches concurrently.
    in_flight = 0
    max_in_flight = 0
    held: list[tuple[int, int]] = []

    class ConcurrentHolder(HoldsRows):
        async def render_rows(self, waiting):
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return tuple(item * 10 for item in waiting)

        def hold_row(self, waiting, row) -> None:
            held.append((waiting, row))

    asyncio.run(ConcurrentHolder().render_and_hold(range(8), batch=4))
    assert max_in_flight == 2
    assert held == [(i, i * 10) for i in range(8)]

    # 2. Tapping within vertical touch slop of a header sender/target name opens the target
    #    rather than collapsing the message, and `pinned_dividers` preserves the `▼ ` arrow.
    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings()).at_width(42)
    msg = Message(sender="toad-qt", target="#comms", body="Body", type=InfoKind)
    frag = transcript_fragments(
        (IncomingTranscript.of(msg, reader="user"),),
        resolve_sent=lambda _r: {},
        classes=QT_FRAGMENT_CLASSES,
        files=NO_PAGE_FILES,
    )[0]
    assert len(frag.pinned_dividers) == 1
    assert frag.pinned_dividers[0].spans[0].text == "▼ "
    assert isinstance(frag.pinned_dividers[0].spans[0].link, FragmentCollapse)

    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setTextWidth(360)
    doc.setHtml(renderer.html(frag.line_blocks))
    layout = doc.documentLayout()

    sender_pts = [
        (x, y)
        for y in range(0, 60)
        for x in range(0, 360, 2)
        if "toad-qt" in layout.anchorAt(QPoint(x, y))
    ]
    assert sender_pts
    mid_x = (min(x for x, _ in sender_pts) + max(x for x, _ in sender_pts)) // 2
    just_below_y = max(y for _, y in sender_pts) + 4

    fake_win = MagicMock()
    fake_win.model_rows.fragments = (frag,)
    fake_win.row_rect.return_value = QRect(0, 0, 360, int(doc.size().height()))
    fake_win.rows.layout_width.return_value = 360
    fake_win.rows.row_document_for.return_value = doc
    fake_win._TOUCH_LINK_OFFSETS = QtHistoryWindow._TOUCH_LINK_OFFSETS
    fake_win._tapped_link_in_document = lambda d, x, y, w, h: QtHistoryWindow._tapped_link_in_document(fake_win, d, x, y, w, h)
    picked = QtHistoryWindow._tapped_link_at(fake_win, 0, QPoint(mid_x, just_below_y))
    assert picked is not None
    link, href = picked
    assert link == OpenTarget("toad-qt")

    # 3. TapHighlight inverts exact tapped text/header foreground & background inside QTextDocument.
    bg, fg = QColor("#111111"), QColor("#eeeeee")
    link_hl = RowLinkTapHighlight(frag.key, href)
    assert link_hl.matches_row(frag.key) is True
    assert link_hl.matches_row(("other", 0)) is False
    link_sels = link_hl.selections(doc, bg, fg)
    assert link_sels, "tapped link must produce inverted QTextDocument selections"
    assert all(sel.format.foreground().color() == bg for sel in link_sels)
    assert all(sel.format.background().color() != bg for sel in link_sels)
    assert any("toad-qt" in sel.cursor.selectedText() for sel in link_sels)

    header_hl = RowHeaderTapHighlight(frag.key)
    header_sels = header_hl.selections(doc, bg, fg)
    assert header_sels, "tapped header divider must invert header text runs"
    assert all(sel.format.foreground().color() == bg for sel in header_sels)
    assert any("▼" in sel.cursor.selectedText() for sel in header_sels)

    # Sticky header keeps WA_TransparentForMouseEvents=True and dispatches both link taps and collapse taps.
    pinned_doc = QTextDocument()
    pinned_doc.setDocumentMargin(0)
    pinned_doc.setTextWidth(360)
    pinned_doc.setHtml(renderer.html(frag.pinned_dividers))
    sticky_parent = QWidget()
    fake_win.open_pinned.return_value = False
    fake_win.top_page.return_value.collapse_link.return_value = frag.collapse_link
    sticky = QtStickyHeader.__new__(QtStickyHeader)
    QWidget.__init__(sticky, sticky_parent)
    sticky.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    sticky.history_window = fake_win
    sticky.documents = (pinned_doc,)
    sticky.resize(360, int(pinned_doc.size().height()))
    try:
        assert sticky.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is True
        # Tap on `@sender` inside pinned header -> PinnedLinkTapHighlight + dispatch_sync(OpenTarget).
        pinned_sender = [
            (x, y)
            for y in range(0, int(pinned_doc.size().height()))
            for x in range(0, 360, 2)
            if "toad-qt" in pinned_doc.documentLayout().anchorAt(QPoint(x, y))
        ]
        assert pinned_sender
        px = (min(x for x, _ in pinned_sender) + max(x for x, _ in pinned_sender)) // 2
        py = (min(y for _, y in pinned_sender) + max(y for _, y in pinned_sender)) // 2
        assert sticky.handle_tap(QPoint(px, py)) is True
        assert isinstance(fake_win._set_tap_highlight.call_args[0][0], PinnedLinkTapHighlight)
        fake_win.dispatch_sync.assert_called_with(OpenTarget("toad-qt"))

        # Tap on outer divider rule (x=2) -> PinnedHeaderTapHighlight + toggle_fragment.
        fake_win._set_tap_highlight.reset_mock()
        assert sticky.handle_tap(QPoint(2, py)) is True
        assert isinstance(fake_win._set_tap_highlight.call_args[0][0], PinnedHeaderTapHighlight)
        fake_win.toggle_fragment.assert_called_with(frag.collapse_link)
    finally:
        sticky_parent.deleteLater()

    # _clear_tap_highlight resets to NO_TAP_HIGHLIGHT and invalidates the tapped row.
    fake_win.widget_gone = False
    fake_win.tap_highlight = link_hl
    fake_win._tap_highlight_timer = MagicMock()
    fake_win.model_rows.row_of.return_value = 0
    fake_win._invalidate_tap_highlight = lambda hl: QtHistoryWindow._invalidate_tap_highlight(fake_win, hl)
    QtHistoryWindow._clear_tap_highlight(fake_win)
    assert fake_win.tap_highlight is NO_TAP_HIGHLIGHT
    fake_win.update_row.assert_called_with(0)

    # 4. QtToadApp._resync_safe_area restores resting bottom margin after IME file hits 0
    #    even when Qt's cached safeAreaMargins() still holds the old 320 dp folded IME inset.
    inset_file = tmp_path / "ime_bottom_px"
    inset_file.write_text("0", encoding="ascii")
    monkeypatch.setenv("TOAD_IME_INSET_FILE", str(inset_file))
    fake_app = MagicMock()
    fake_app._safe_area_resync_pending = True
    fake_app._rest_bottom_margin = 24
    fake_app._keyboard_open = True
    fake_app.KEYBOARD_MARGIN_THRESHOLD = QtToadApp.KEYBOARD_MARGIN_THRESHOLD
    fake_app.devicePixelRatioF.return_value = 3.0
    fake_app._android_ime_bottom_dp = lambda: QtToadApp._android_ime_bottom_dp(fake_app)
    fake_app.windowHandle.return_value.safeAreaMargins.return_value = QMargins(0, 48, 0, 320)
    fake_app.fit_safe_area = lambda m: QtToadApp.fit_safe_area(fake_app, m)
    QtToadApp._resync_safe_area(fake_app)
    assert fake_app._safe_area_resync_pending is False
    assert fake_app.setContentsMargins.call_args[0][0].bottom() == 24
    assert fake_app._keyboard_open is False


def test_wave2_scroll_perf_coalesced_loop_holds_async_opaque_scrollbar_and_row_fit(monkeypatch) -> None:
    """Covers wave-2 scroll optimizations: `CoalescedQEventLoop` coalesces zero-delay
    callbacks onto one QTimer drain, `RemoteCoreConnection.holds_async` skips `run_thread`,
    `OverlayScrollBar` sets `WA_OpaquePaintEvent`, and `RowFittedTree.fit_rows` skips
    redundant `doItemsLayout()` calls when tree structure is unchanged."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    import asyncio
    import inspect
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea, QTreeWidget, QTreeWidgetItem
    from toad.client.connection import RemoteCoreConnection
    from toad.markdown_links import ReferenceContext
    from toad.qt.client_start import CoalescedQEventLoop
    from toad.qt.window import RowFittedTree

    # 1. CoalescedQEventLoop drains multiple call_soon handles in one QTimer tick.
    app.setQuitOnLastWindowClosed(False)
    app.processEvents()
    loop = CoalescedQEventLoop(app)
    try:
        ran: list[int] = []
        starts = 0
        orig_start = loop._ready_timer.start

        def count_start(*args):
            nonlocal starts
            starts += 1
            return orig_start(*args)

        loop._ready_timer.start = count_start
        for i in range(10):
            loop.call_soon(ran.append, i)
        assert starts == 1
        loop.run_until_complete(asyncio.sleep(0.01))
        assert ran == list(range(10))
    finally:
        loop.close()

    # 2. RemoteCoreConnection.holds_async checks in-memory observation without run_thread.
    fake_runtime = MagicMock()
    fake_access = MagicMock()
    fake_access.observation.observed.return_value.observes.return_value = True
    fake_remote = MagicMock(spec=RemoteCoreConnection)
    fake_remote.holds.side_effect = lambda acc, src: RemoteCoreConnection.holds(fake_remote, acc, src)
    assert asyncio.run(RemoteCoreConnection.holds_async(fake_remote, fake_runtime, fake_access, "/bus")) is True
    fake_runtime.run_thread.assert_not_called()

    # 3. OverlayScrollBar sets WA_OpaquePaintEvent and supports watch_geometry=False.
    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())
    clock = AnimationClock(lambda _interval: None)
    area = QScrollArea()
    bar = OverlayScrollBar.follow(area, clock, renderer, 6, watch_geometry=False)
    assert bar is not None
    assert bar.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent) is True
    assert bar.geometry_watch is None
    area.deleteLater()

    # 4. RowFittedTree.fit_rows skips doItemsLayout when structure and width are unchanged.
    class _TestFittedTree(RowFittedTree, QTreeWidget):
        most_rows = 4

    tree = _TestFittedTree()
    tree.setHeaderHidden(True)
    tree.resize(200, 40)
    tree.addTopLevelItem(QTreeWidgetItem(["#comms"]))
    layouts = 0
    orig_layout = tree.doItemsLayout

    def count_layout():
        nonlocal layouts
        layouts += 1
        return orig_layout()

    tree.doItemsLayout = count_layout
    tree.fit_rows()
    tree.fit_rows()
    tree.fit_rows()
    assert layouts == 1
    tree.addTopLevelItem(QTreeWidgetItem(["#model"]))
    tree.fit_rows()
    assert layouts == 2
    tree.deleteLater()

    # 5. Same-height receipt updates keep `_moves_rows == False` (zero full relayout flicker)
    #    even when QTextDocument height is fractional (ceil == ceil, keep_row_size populated).
    from PySide6.QtCore import QSizeF
    from PySide6.QtGui import QFont
    from pyqt_reactive.widgets.virtual_rows import HtmlRow
    from toad.qt.history import HistoryRowDelegate, RowPictures

    delegate = HistoryRowDelegate(renderer, RowPictures(1024 * 1024), MagicMock())
    font = QFont()
    delegate._row_sizes_for = (font.key(), 300)
    delegate._row_sizes = [None]
    old_key = (("k1", "sent", 1), 0, "f", 300)
    new_key = (("k1", "read", 1), 0, "f", 300)
    delegate._prepared[old_key] = HtmlRow("<p>hello</p>")
    delegate.last_shown[delegate.row_identity(old_key)] = old_key
    fake_doc = MagicMock()
    fake_doc.size.return_value = QSizeF(300.0, 42.3)  # fractional height: ceil=43, int=42
    delegate.laid_out = lambda _k, _f, _w, _fmt: fake_doc
    delegate.preparation_key_for = lambda _frag, _f, _w: new_key
    delegate.row_preparation = lambda _frag, _f, _w: (lambda: None)
    delegate.keyed_formatting = lambda _k, _t, _p: MagicMock(final=False)
    fake_frag = MagicMock(has_blocks=True, clipboard_text="hello")
    height, _extent, est = delegate.measure_row(0, fake_frag, font, 300, allow_estimate=False)
    assert est is False
    assert height == 43 + delegate.ROW_PADDING
    assert new_key not in delegate._metrics
    assert delegate._moves_rows(new_key, HtmlRow("<p>hello</p>"), awaited=True) is False
    app.processEvents()


def test_wave3_android_scroll_zero_css_spans_matched_qimage_tiles_and_pause_measure(monkeypatch) -> None:
    """Wave-3 Android scroll fixes:
    1. `QtLineRenderer.styled`/`code_spans`/`rich_text` emit `<font color>` + `<b>`/`<i>`/`<u>`
       with merged same-style runs and zero `<span style=`, bypassing `QCss::Parser::parse`.
    2. `HistoryRowDelegate.paint_pictures` renders tiles as backing-store-matched `QImage`s
       and blits non-fading tiles with `CompositionMode_Source`.
    3. `HistoryRowDelegate.set_scroll_paused` pauses `_measure_slice` mid-fling and resumes it
       once scrolling settles.
    4. `QtConversationHistory.draws_rows` answers from `shown_fragments` without calling
       `page.line_count` / `fragment_height` / `QTextDocument.setHtml` on scroll frames.
    """
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    import inspect
    from PySide6.QtCore import QModelIndex, QRect
    from PySide6.QtGui import QFont, QImage, QPainter, QRegion, QTextDocument
    from PySide6.QtWidgets import QStyleOptionViewItem
    from toad.client.line_blocks import UserRole
    from toad.markdown_links import ReferenceContext
    from toad.qt.history import HistoryRowDelegate, QtConversationHistory, RowPictures

    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())

    # 1. Zero `<span style=` in styled() and code_spans(), plus merged runs.
    styled_html = renderer.styled("hello", UserRole)
    assert "<font color=" in styled_html and "<span style=" not in styled_html
    code_html = renderer.code_spans("x = 1 + 2\ny = x * 3\n", "python")
    assert "<span style=" not in code_html and "x" in code_html

    # 2. Backing-store-matched QImage tiles painted with CompositionMode_Source.
    pictures = RowPictures(8 * 1024 * 1024)
    delegate = HistoryRowDelegate(renderer, pictures, MagicMock())
    doc = QTextDocument()
    doc.setPlainText("hello world")
    delegate.final_document_for = lambda _frag, _font, _w: doc
    fake_frag = MagicMock(key="r1", has_blocks=True, clipboard_text="hello world")

    surface = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(surface)
    try:
        assert delegate.paint_pictures(
            painter, fake_frag, QRect(0, 0, 200, 40), QRegion(QRect(0, 0, 200, 100))
        ) is True
    finally:
        painter.end()
    assert len(pictures.rows) == 1
    stored_img = next(iter(pictures.rows.values()))[2]
    assert isinstance(stored_img, QImage)
    assert stored_img.format() == QImage.Format.Format_ARGB32_Premultiplied

    # 3. _measure_slice defers while scroll-paused and resumes when unpaused.
    delegate._unmeasured.add(0)
    delegate.set_scroll_paused(True)
    delegate._measure_slice()  # must not touch view/model while paused
    assert len(delegate._unmeasured) == 1
    delegate.set_scroll_paused(False)
    assert delegate._measure_timer.isActive()
    delegate._measure_timer.stop()

    # 4. QtConversationHistory.draws_rows never touches page.line_count.
    class _ExplodingPage:
        shown_fragments = (MagicMock(has_blocks=True),)

        @property
        def line_count(self):
            raise AssertionError("draws_rows must not invoke page.line_count")

    fake_history = MagicMock()
    fake_history.pages = (_ExplodingPage(),)
    assert QtConversationHistory.draws_rows.fget(fake_history) is True
    app.processEvents()


def test_wave4_virtual_row_canvas_direct_value_and_tab_chrome_cache(monkeypatch) -> None:
    """Wave-4 Android FPS architectural overhaul:
    1. `VirtualRowCanvas` provides O(log N) prefix-sum lookup, handles 0-height collapsed
       parts, tail appends, and paints only visible rows without `QListView`.
    2. `DirectValue.deliver` / `deliver_accepted` bypass `asyncio.to_thread` / `_QThreadWorker`.
    3. `QtSessionTabBar` caches empty-text busy-tab chrome `QImage`s across wave ticks.
    4. `ActivitySweep._scheme_colours()` caches resolved scheme RGB tuples across frames.
    """
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    import asyncio
    import inspect
    from types import SimpleNamespace
    from PySide6.QtGui import QColor, QFont
    from pyqt_reactive.widgets.virtual_rows import HtmlRow
    from toad.markdown_links import ReferenceContext
    from toad.qt.activity import ActivitySweep
    from toad.qt.history import HistoryRowDelegate, RowPictures
    from toad.qt.virtual_scroll import VirtualRowCanvas
    from toad.work_preparation import DirectValue

    # 1. VirtualRowCanvas prefix-sum layout, collapsed 0-height rows, and tail splice.
    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())
    delegate = HistoryRowDelegate(renderer, RowPictures(4 * 1024 * 1024), MagicMock())
    canvas = VirtualRowCanvas(delegate)
    canvas.resize(320, 400)
    canvas.show()
    try:
        rows = tuple(
            SimpleNamespace(
                key=f"r{i}",
                shown="s",
                revision=1,
                has_blocks=(i % 7 != 0),
                clipboard_text=f"Row {i}",
                line_blocks=(),
                header_blocks=0,
                pinned_dividers=(),
            )
            for i in range(60)
        )
        font = canvas.font()
        width = canvas.viewport_width()
        for r in rows:
            if r.has_blocks:
                delegate._prepared[delegate.fragment_key(r, font, width)] = HtmlRow(f"<p>{r.clipboard_text}</p>")
        canvas.model_rows.show(rows)
        canvas.execute_layout()
        assert canvas.total_height() > 0
        # Row 0 has has_blocks=False (0 height), so y=0 maps to row 1 (first positive-height row).
        assert canvas.row_at_y(0) == 1
        assert canvas.row_rect(0).isEmpty()
        r1 = canvas.row_rect(1)
        assert r1.top() == 0 and r1.height() > 0
        assert canvas.row_at_y(r1.height() - 1) == 1
        assert canvas.row_at_y(r1.height()) == 2
        # Tail append preserves prefix and extends offsets cleanly.
        extra = SimpleNamespace(
            key="r60", shown="s", revision=1, has_blocks=True,
            clipboard_text="Row 60", line_blocks=(), header_blocks=0, pinned_dividers=(),
        )
        delegate._prepared[delegate.fragment_key(extra, font, width)] = HtmlRow("<p>Row 60</p>")
        prev_total = canvas.total_height()
        canvas.model_rows.show(rows + (extra,))
        canvas.execute_layout()
        assert canvas.total_height() > prev_total
        assert canvas.model_rows.row_of("r60") == 60
        canvas.grab()
    finally:
        delegate.cleanup()
        canvas.deleteLater()

    # 2. DirectValue delivers synchronously without calling scheduler.run_thread / to_thread.
    scheduler = MagicMock()
    dv = DirectValue("ready")
    assert asyncio.run(dv.deliver(scheduler)) == "ready"
    scheduler.run_thread.assert_not_called()
    task = MagicMock()
    task.accept_result.side_effect = lambda v: f"accepted:{v}"
    assert asyncio.run(dv.deliver_accepted(task)) == "accepted:ready"
    task.accept_result.assert_called_once_with("ready")

    # 3. QtSessionTabBar caches busy-tab QSS chrome QImage across wave frames.
    clock = AnimationClock(lambda _interval: None, now=lambda: 0.5)
    bar = QtSessionTabBar(clock, QColor("#ff00ff"), QColor("#ffffff"))
    bar.show_tabs([("#comms", "comms")])
    bar.follow_tabs((SimpleNamespace(mode_name="comms", busy=True),))
    bar.resize(300, 36)
    bar.show()
    try:
        bar.grab()
        assert len(bar._tab_chrome) == 1
        cached_chrome = next(iter(bar._tab_chrome.values()))
        bar.grab()
        assert len(bar._tab_chrome) == 1
        assert next(iter(bar._tab_chrome.values())) is cached_chrome
    finally:
        bar.follow_tabs((SimpleNamespace(mode_name="comms", busy=False),))
        bar.deleteLater()

    # 4. ActivitySweep caches scheme colour tuples and paints a live sweep frame cleanly.
    sweep = ActivitySweep(renderer, clock)
    sweep.resize(300, 20)
    sweep.show()
    try:
        c1 = sweep._scheme_colours()
        c2 = sweep._scheme_colours()
        assert c1[0] is c2[0] and c1[1] is c2[1] and c1[2] is c2[2]
        sweep.sweep(True)
        sweep.grab()
        assert len(c1[2]) >= 1
    finally:
        sweep.sweep(False)
        sweep.deleteLater()
    app.processEvents()


def test_first_collapse_prepares_inline_without_worker_pool(monkeypatch) -> None:
    """Collapsing a message prepares its lightweight header + 1-line summary inline with the
    warm renderer (zero RenderProcessPool submission) and `compact_preview` bounds huge bodies."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from types import SimpleNamespace
    from agent_comms.messaging.display_references import ProjectReferences
    from toad.client.line_blocks import Divider, IncomingRole, MarkdownBody, MutedRole, Span, Summary
    from toad.client.structured_context import compact_preview
    from toad.qt.history import HistoryRowDelegate, RowPictures

    # 1. compact_preview stays O(1) on huge bodies with leading whitespace.
    huge = ("   \n\t  ") + ("hello world " * 20000)
    assert compact_preview(huge, 40) == "hello world hello world hello world hel…"

    # 2. prepare_inline renders collapsed Divider+Summary rows synchronously without touching
    #    the RenderProcessPool, and skips MarkdownBody rows so heavy bodies stay off-loop.
    scheme = current_scheme(os.environ)
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), ProjectReferences()), DiffSettings())
    processes = MagicMock()
    delegate = HistoryRowDelegate(renderer, RowPictures(1024 * 1024), processes)
    font = app.font()
    collapsed_header = Divider((Span("▶ ", IncomingRole), Span("#model", IncomingRole)), role=IncomingRole)
    collapsed_summary = Summary((Span("preview line", MutedRole),))

    collapsed_frag = SimpleNamespace(
        key="m-1",
        shown=("collapsed",),
        revision=0,
        has_blocks=True,
        line_blocks=(collapsed_header, collapsed_summary),
        header_blocks=1,
        pinned_dividers=(collapsed_header,),
    )
    assert delegate.prepare_inline(collapsed_frag, font, 360) is True
    assert delegate.is_prepared(delegate.fragment_key(collapsed_frag, font, 360)) is True
    assert delegate.is_prepared(delegate.header_key(collapsed_header, font, 360)) is True
    processes.submit.assert_not_called()

    markdown_frag = SimpleNamespace(
        key="m-2",
        shown=("expanded",),
        revision=0,
        has_blocks=True,
        line_blocks=(collapsed_header, MarkdownBody("big body")),
        header_blocks=1,
        pinned_dividers=(collapsed_header,),
    )
    assert delegate.prepare_inline(markdown_frag, font, 360) is False
    assert delegate.is_prepared(delegate.fragment_key(markdown_frag, font, 360)) is False
    delegate.cleanup()


def test_header_tap_highlight_inverts_bars_and_multiline_and_text_buttons_share_tap_flash(monkeypatch) -> None:
    """Header tap flash inverts horizontal `<hr>` bars + all wrapped/timestamp lines on both
    in-flow and pinned headers, and clickable text buttons inherit the shared `TapFeedback` /
    `TapFlashControl` owner."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QTextDocument
    from agent_comms.messaging.display_references import ProjectReferences
    from ui_theme.catalog import SCHEMES
    from ui_theme.scheme import BackgroundColour, SecondaryColour

    from toad.client.line_blocks import Divider, EventTime, IncomingRole, MutedRole, Span, Summary
    from toad.client.tap_flash import TAP_FLASH_MS, TapFeedback
    from toad.qt.channel_sort import QtSortButton
    from toad.qt.goal import QtGoalControl
    from toad.qt.queue_ui import QtActivatedText
    from toad.qt.side_bar import QtSidebarAction
    from toad.qt.tap_flash import QtPushButton, QtTextButton, TapFlashControl
    from toad.qt.virtual_scroll import (
        PinnedHeaderTapHighlight,
        RowHeaderTapHighlight,
        _divider_tables,
    )

    # 1. Single nominal ancestor across document tap highlights AND clickable text controls.
    for cls in (
        RowHeaderTapHighlight,
        PinnedHeaderTapHighlight,
        TapFlashControl,
        QtTextButton,
        QtPushButton,
        QtGoalControl,
        QtSortButton,
        QtSidebarAction,
        QtActivatedText,
    ):
        assert issubclass(cls, TapFeedback)
        assert cls.tap_flash_duration_ms == TAP_FLASH_MS

    # 2. HeaderTapHighlight inverts BOTH horizontal `<hr>` bars AND multi-line timestamp rows.
    ts_cls = [c for c in EventTime.__subclasses__() if c.__name__ != "UnrecordedEventTime"][0]
    scheme = SCHEMES[0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), ProjectReferences()), DiffSettings()).at_width(30)
    div = Divider(
        (Span("▼ ", IncomingRole), Span("#model <- pm-neuro-arch", IncomingRole)),
        role=IncomingRole,
        timestamp=ts_cls(1795744971.0),
    )
    html = renderer.html((div, Summary((Span("body line", MutedRole),))))
    doc = QTextDocument()
    doc.setTextWidth(360)
    doc.setHtml(html)
    tables = _divider_tables(doc)
    assert len(tables) >= 2  # title + timestamp tables

    bg = QColor(BackgroundColour.rgb(scheme).hex)
    fg = QColor("#ffffff")
    ink = QColor(renderer.colour(IncomingRole))
    img = QImage(360, int(doc.size().height()) + 4, QImage.Format.Format_ARGB32)
    img.fill(bg)
    painter = QPainter(img)
    RowHeaderTapHighlight("m-1").paint_document(painter, doc, QPalette(), bg, fg)
    painter.end()

    layout = doc.documentLayout()
    for table, _hr_color in tables:
        trect = layout.frameBoundingRect(table)
        # Band background inside left & right rule cells is inverted to `ink`.
        for col in (0, 2):
            brect = layout.blockBoundingRect(table.cellAt(0, col).firstCursorPosition().block())
            mid_x = int(brect.center().x())
            assert img.pixelColor(mid_x, int(trect.top()) + 2) == ink
            # Horizontal bar itself is drawn inverted in `bg` across the `ink` band.
            assert img.pixelColor(mid_x, int(brect.center().y())) == bg

    # 3. QtTextButton flashes inverted (`SecondaryColour` background) on tap and clears cleanly.
    btn = QtTextButton()
    btn.setText("Pause")
    btn.apply_text_style(renderer, SecondaryColour)
    btn.resize(80, 32)
    btn.show()
    app.processEvents()
    btn.flash_tap()
    flashed = btn.grab().toImage()
    sec_color = QColor(SecondaryColour.rgb(scheme).hex)
    assert flashed.pixelColor(4, 4) == sec_color
    btn._end_tap_flash()
    assert btn._tap_flashing is False
    btn.deleteLater()


def test_unified_viewport_arrival_glides_tall_and_empty_messages_in_lockstep(monkeypatch):
    """One unified `ViewportArrival` drives BOTH translation and opacity (`0 -> 1`) on
    `FOLLOW_ARRIVAL`:
    1. Tall messages (`ArrivalPosition` taller than viewport) glide smoothly from below the
       viewport up to their head (`destination < tail_scroll_y`) while fading in lockstep,
       never overshooting to the bottom, and release tail-following on land.
    2. Empty / non-scrolling viewports (`tail_scroll_y == 0`) translate the arriving row
       smoothly upward (`offset_y: slide -> 0`) as `opacity` rises `0 -> 1` in lockstep,
       and `HistoryRowDelegate` + `VirtualRowCanvas` paint it cleanly without ghosting.
    3. `TapHighlight` crossing targets (`RowTapTarget`/`PinnedTapTarget`) and `ViewportCanvas`
       (`DetachedCanvas`/`VirtualRowCanvas`) share clean MI bases without restated members."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from contextlib import nullcontext
    from dataclasses import dataclass
    from PySide6.QtGui import QColor, QImage, QPainter
    from toad.arrivals import (
        AnimatesArrivals,
        SETTLED_ARRIVAL,
        ViewportArrival,
        ViewportArrivalState,
    )
    from toad.client.history_changes import NO_HISTORY_CHANGE
    from toad.client.line_blocks import Span, Summary, TextRole
    from toad.client.reader_position import (
        ArrivalPosition,
        HeadArrivalTarget,
        RowPosition,
        TailPosition,
    )
    from toad.markdown_links import LinkContext, ReferenceContext
    from toad.qt.history import HistoryRowDelegate, RowPictures
    from toad.qt.lines import QtLineRenderer
    from toad.qt.theme import SCHEMES
    from toad.qt.virtual_scroll import (
        DetachedCanvas,
        PinnedHeaderTapHighlight,
        PinnedLinkTapHighlight,
        PinnedTapTarget,
        RowHeaderTapHighlight,
        RowLinkTapHighlight,
        RowTapTarget,
        ViewportCanvas,
        VirtualRowCanvas,
    )
    import inspect

    # 1. MI lattice checks (TapHighlight crossing + ViewportCanvas).
    assert issubclass(RowLinkTapHighlight, RowTapTarget)
    assert issubclass(RowHeaderTapHighlight, RowTapTarget)
    assert issubclass(PinnedLinkTapHighlight, PinnedTapTarget)
    assert issubclass(PinnedHeaderTapHighlight, PinnedTapTarget)
    assert issubclass(DetachedCanvas, ViewportCanvas)
    assert issubclass(VirtualRowCanvas, ViewportCanvas)

    # 2. Tall arrival glides smoothly from bottom edge (1400) up to its head (2000 < tail 2300)
    #    while fading 0 -> 1 on ONE `ViewportArrival`, then releases tail anchor on land.
    @dataclass(frozen=True)
    class _Frag:
        key: str
        source_identity: str

    class _TallLoc:
        def __init__(self, head_y: float, height: int) -> None:
            self._head_y = head_y
            self.fragment = height

        def laid_out(self, _window) -> bool:
            return True

        def location(self):
            return self

        def destination(self, _window, _fraction: float) -> float:
            return self._head_y

    class _TallPage:
        def __init__(self, head_y: float, height: int) -> None:
            self._loc = _TallLoc(head_y, height)

        def fragment_row(self, _key, _block: int):
            return self._loc

        def drawn_height(self, height: int) -> int:
            return height

    class _ProbeWindow(AnimatesArrivals):
        arrival_slide_distance = 36.0
        history_change = NO_HISTORY_CHANGE

        def __init__(self, *, scroll_y: float, tail_scroll_y: float, row_height: float, viewport_h: int) -> None:
            self._now = 0.0
            self._clock = AnimationClock(lambda _dt: None, now=lambda: self._now)
            self.follows_tail = True
            self.scroll_y = scroll_y
            self.tail_scroll_y = tail_scroll_y
            self._row_height = row_height
            self._viewport_h = viewport_h
            self.reader_position = TailPosition()
            self.anchor_released = False
            self.repainted: list[tuple[object, ...]] = []

        @property
        def animation_clock(self) -> AnimationClock:
            return self._clock

        @property
        def arrival_animation_visible(self) -> bool:
            return True

        def layout_scroll(self):
            return nullcontext()

        def arrival_rows_height(self, keys: tuple[object, ...]) -> float | None:
            return self._row_height * len(keys)

        def repaint_arrival_keys(self, keys: tuple[object, ...]) -> None:
            self.repainted.append(keys)

        def message_too_tall(self, height: int) -> bool:
            return height > self._viewport_h

        def release_anchor(self) -> None:
            self.follows_tail = False
            self.anchor_released = True

        def top_page(self):
            class _Top:
                def reader_position(self, win):
                    return RowPosition(win.scroll_y)
            return _Top()

    tall_win = _ProbeWindow(scroll_y=1400.0, tail_scroll_y=2300.0, row_height=900.0, viewport_h=600)
    tall_pos = ArrivalPosition(_TallPage(head_y=2000.0, height=900), "tall-1")
    tall_win.reader_position = tall_pos
    assert isinstance(tall_pos.arrival_target(tall_win), HeadArrivalTarget)

    tall_win.arrive_fragments((_Frag("tall-1", "src-tall"),), live=False)
    assert len(tall_win.arrivals) == 1
    arrival = tall_win.arrivals[0]
    assert isinstance(arrival, ViewportArrival)
    assert tall_win.glide is arrival
    assert tall_win.scroll_y == 1400.0
    start_state = tall_win.arrival_state("tall-1", row_height=900.0)
    assert start_state == ViewportArrivalState(opacity=0.0, offset_y=0.0, active=True)

    # Mid-flight: scroll moves smoothly toward head (2000) while opacity rises in lockstep,
    # never reaching tail_scroll_y (2300).
    arrival.apply_amount(0.5)
    assert tall_win.scroll_y == 1700.0
    assert tall_win.scroll_y < tall_win.tail_scroll_y
    mid_state = tall_win.arrival_state("tall-1", row_height=900.0)
    assert mid_state.opacity == 0.5 and mid_state.offset_y == 0.0 and mid_state.active is True

    # Landing: finishes both scroll and fade together at head (2000) and releases tail follow.
    arrival.land()
    assert tall_win.scroll_y == 2000.0
    assert tall_win.anchor_released is True
    assert tall_win.follows_tail is False
    assert tall_win.glide is None
    assert not tall_win.has_active_arrivals
    assert tall_win.arrival_state("tall-1", row_height=900.0) == SETTLED_ARRIVAL

    # 3. Empty/non-scrolling viewport (`tail_scroll_y == 0`): local upward slide (`offset_y`)
    #    shrinks `36 -> 18 -> 0` in lockstep with `opacity: 0 -> 0.5 -> 1`.
    empty_win = _ProbeWindow(scroll_y=0.0, tail_scroll_y=0.0, row_height=48.0, viewport_h=600)
    empty_win.arrive_fragments((_Frag("first-1", "src-first"),), live=False)
    empty_arrival = empty_win.arrivals[0]
    s0 = empty_win.arrival_state("first-1", row_height=48.0)
    assert s0.active is True and s0.opacity == 0.0 and s0.offset_y == 36.0
    empty_arrival.apply_amount(0.5)
    s5 = empty_win.arrival_state("first-1", row_height=48.0)
    assert s5.active is True and s5.opacity == 0.5 and s5.offset_y == 18.0
    empty_arrival.land()
    assert empty_win.arrival_state("first-1", row_height=48.0) == SETTLED_ARRIVAL

    # 4. Qt VirtualRowCanvas + HistoryRowDelegate paints a sliding + fading row cleanly.
    scheme = SCHEMES[0]
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())

    class _InlineFrag:
        key = "row-0"
        shown = None
        revision = 0
        has_blocks = True
        line_blocks = (Summary((Span("Hello sliding world", TextRole),)),)
        header_blocks = 0
        pinned_dividers = ()
        clipboard_text = "Hello sliding world"

        def row_identity(self):
            return "row-0"

        def plain_text(self):
            return "Hello sliding world"

    class _TestCanvas(VirtualRowCanvas):
        arrival_slide_distance = 36.0

        def __init__(self, store):
            super().__init__(store)
            self._state = SETTLED_ARRIVAL

        @property
        def has_active_arrivals(self) -> bool:
            return self._state.active

        def arrival_state(self, key: object, row_height: float = 0.0) -> ViewportArrivalState:
            return self._state if key == "row-0" else SETTLED_ARRIVAL

    delegate = HistoryRowDelegate(renderer, RowPictures(1_000_000), MagicMock())
    frag = _InlineFrag()
    canvas = _TestCanvas(delegate)
    canvas.resize(320, 200)
    canvas.show()
    app.processEvents()
    assert delegate.prepare_inline(frag, canvas.font(), canvas.viewport_width()) is True
    canvas.model_rows.show((frag,))
    canvas.do_layout()
    app.processEvents()
    try:
        # Mid-slide (offset_y=18, opacity=0.5): viewport grabs cleanly without crash or clip.
        canvas._state = ViewportArrivalState(opacity=0.5, offset_y=18.0, active=True)
        mid_img = canvas.viewport().grab().toImage()
        # Settled: offset_y=0, opacity=1.0 — resting pixels are clean and distinct from shifted mid-slide.
        canvas._state = SETTLED_ARRIVAL
        end_img = canvas.viewport().grab().toImage()
        assert mid_img != end_img
    finally:
        canvas.deleteLater()
        app.processEvents()


def test_qt_bus_switcher_activates_rows_closes_on_submit_and_preserves_launch_connection(monkeypatch):
    """Qt bus switching works cleanly on both Android (remote-only) and desktop (local + remote):
    1. Clicking a `BusRow` in `QtBusSwitcher` closes the switcher and calls `host.open_bus(choice)`
       polymorphically via `activate_in_switcher` (no `AttributeError: _BusRow`).
    2. Clicking an `OpenSection` header toggles expansion without closing the switcher.
    3. Pressing Enter in `BusAddress` asks the typed host and hides the switcher; `Esc` hides it.
    4. `RemoteCoreConnection.offered_buses` omits `LocalBus` while `LocalCoreConnection.offered_buses`
       includes it, and `QtToadApp.connection_for` preserves `_launch_connection.chosen` after
       switching onto a remote bus so desktop can always switch back to `"This machine"`."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from types import SimpleNamespace
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from toad.client.bus_selection import BusChoice, LocalBus
    from toad.client.connection import RemoteCoreConnection
    from toad.client.local_connection import LocalCoreConnection
    from toad.markdown_links import LinkContext, ReferenceContext
    from toad.qt.bus_switcher import QtBusSwitcher
    from toad.qt.window import BusRow, OpenSection, QtToadApp
    from toad.client.session_tracker import SidebarState
    import inspect

    from pyqt_reactive.theming import ColorScheme
    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())

    opened: list[BusChoice] = []
    asked: list[str] = []
    registered: list[object] = []

    class _FakeHost(QWidget):
        found_buses = ()

        def __init__(self) -> None:
            super().__init__()
            self.renderer = renderer
            self.theme = SimpleNamespace(color_scheme=ColorScheme.from_theme(scheme))
            self.animation_clock = AnimationClock(lambda _dt: None)
            self.sidebar_state = SidebarState()
            self.discovered = 0

        def open_bus(self, choice: BusChoice) -> None:
            opened.append(choice)

        def ask_typed_host(self, typed: str) -> None:
            if typed.strip():
                asked.append(typed.strip())

        def offered_buses(self, _now: float) -> tuple[BusChoice, ...]:
            return (LocalBus(),)

        def register_bus_listing(self, listing) -> None:
            registered.append(listing)

        def deregister_bus_listing(self, listing) -> None:
            if listing in registered:
                registered.remove(listing)

        def discover_buses(self) -> None:
            self.discovered += 1

    host = _FakeHost()
    host.show()
    switcher = QtBusSwitcher(host)
    try:
        switcher.show_switcher()
        assert switcher.isVisible() is True
        assert host.discovered == 1
        assert switcher in registered
        section = switcher._tree.topLevelItem(0)
        assert isinstance(section, OpenSection)
        row = section.child(0)
        assert isinstance(row, BusRow)

        # Clicking the section header toggles expansion without hiding the switcher.
        was_expanded = section.isExpanded()
        switcher._row_clicked(section)
        assert section.isExpanded() is (not was_expanded)
        assert switcher.isVisible() is True

        # Clicking a BusRow hides the switcher and invokes host.open_bus(choice).
        switcher._row_clicked(row)
        assert switcher.isVisible() is False
        assert switcher not in registered
        assert opened == [LocalBus()]

        # Pressing Enter in BusAddress asks the typed host and hides the switcher.
        switcher.show_switcher()
        assert switcher.isVisible() is True
        switcher._address.setText("ts-gaming")
        switcher._address.returnPressed.emit()
        assert asked == ["ts-gaming"]
        assert switcher.isVisible() is False

        # Pressing Escape hides the switcher as promised by BusSwitcherPrompt.
        switcher.show_switcher()
        assert switcher.isVisible() is True
        switcher.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        assert switcher.isVisible() is False

        # Remote vs local offered_buses & launch-connection retention in QtToadApp.connection_for.
        monkeypatch.setattr(BusChoice, "held", staticmethod(lambda _now: ()))
        assert RemoteCoreConnection.offered_buses(object(), 0.0) == ()
        assert LocalCoreConnection.offered_buses(object(), 0.0) == (LocalBus(),)

        chosen_args: list[list[str]] = []
        sentinel = object()
        fake_launch = SimpleNamespace(chosen=lambda args: (chosen_args.append(args), sentinel)[1])
        fake_remote = SimpleNamespace(chosen=lambda _args: (_ for _ in ()).throw(ValueError("wrong connection")))
        fake_app = SimpleNamespace(
            _launch_connection=fake_launch,
            coordination_access=SimpleNamespace(connection=fake_remote),
        )
        assert QtToadApp.connection_for(fake_app, LocalBus()) is sentinel
        assert chosen_args == [[]]
    finally:
        switcher.deleteLater()
        host.deleteLater()
        app.processEvents()


def test_fast_tool_commit_adopts_live_arrival_without_snap_or_scroll_jerk():
    """When a fast tool call completes and commits to saved history mid-`ViewportArrival`:
    1. The running `ViewportArrival` adopts the saved fragment's key by `source_identity`
       at its exact current progress (`amount`), so opacity and upward slide continue
       smoothly instead of snapping to `SETTLED_ARRIVAL`.
    2. Neither an adopted live block nor an already-landed live block triggers a second
       `glide_to_end()` that would subtract its height from `tail_scroll_y` and jerk scroll."""
    from contextlib import contextmanager
    from types import SimpleNamespace
    from toad.arrivals import AnimatesArrivals, SETTLED_ARRIVAL
    from toad.client.reader_position import TailPosition

    clock = AnimationClock(lambda _dt: None)

    class _Window(AnimatesArrivals):
        arrival_slide_distance = 36.0

        def __init__(self) -> None:
            self.follows_tail = True
            self.reader_position = TailPosition()
            self.scroll_y = 200.0
            self.tail_scroll_y = 280.0
            self.heights: dict[object, float] = {}
            self.repainted: list[tuple[object, ...]] = []

        @property
        def animation_clock(self) -> AnimationClock:
            return clock

        @property
        def arrival_animation_visible(self) -> bool:
            return True

        def arrival_rows_height(self, keys: tuple[object, ...]) -> float | None:
            found = [self.heights[k] for k in keys if k in self.heights]
            return sum(found) if found else None

        def repaint_arrival_keys(self, keys: tuple[object, ...]) -> None:
            self.repainted.append(keys)

        @contextmanager
        def layout_scroll(self):
            yield

    win = _Window()
    live_frag = SimpleNamespace(key=("live", -1), source_identity="tc-fast")
    saved_frag = SimpleNamespace(key=("saved", 42), source_identity="tc-fast")
    win.heights[live_frag.key] = 80.0
    win.heights[saved_frag.key] = 80.0

    # 1. Live tool starts animating; advance halfway (opacity > 0 and < 1).
    win.arrive_fragments((live_frag,), live=True)
    assert len(win.arrivals) == 1
    arrival = win.arrivals[0]
    arrival.apply_amount(0.4)
    scroll_mid = win.scroll_y
    assert win.arrival_state(live_frag.key, 80.0).opacity == 0.4

    # 2. Fast tool completes and commits to saved history mid-animation.
    win.arrive_fragments((saved_frag,), live=False)
    assert len(win.arrivals) == 1
    assert win.arrivals[0] is arrival
    saved_state = win.arrival_state(saved_frag.key, 80.0)
    assert saved_state.active is True
    assert saved_state.opacity == 0.4
    # No phantom re-glide subtracted height from tail_scroll_y.
    assert win.scroll_y == scroll_mid

    # 3. Arrival lands smoothly to settled state.
    arrival.land()
    assert win.arrival_state(saved_frag.key, 80.0) is SETTLED_ARRIVAL

    # 4. A slow tool whose live arrival already finished commits later: stays rock steady
    #    with no fade and no scroll-backwards jerk.
    slow_live = SimpleNamespace(key=("live", -2), source_identity="tc-slow")
    slow_saved = SimpleNamespace(key=("saved", 43), source_identity="tc-slow")
    win.heights[slow_live.key] = 80.0
    win.heights[slow_saved.key] = 80.0
    win.arrive_fragments((slow_live,), live=True)
    win.arrivals[0].land()
    assert win.arrivals == []
    win.scroll_y = win.tail_scroll_y = 360.0
    win.arrive_fragments((slow_saved,), live=False)
    assert win.arrivals == []
    assert win.glide is None
    assert win.scroll_y == 360.0


def test_place_reader_preserves_active_arrival_glide_and_latest_position_arrived():
    """Channel source replacements (`show_newest`) share the exact same arrival behavior:
    1. `ReaderPlacement.place_reader()` never snaps `scroll_y` while `gliding_to_end()` is True
       (so post-refresh `_complete_latest` -> `LatestPosition.release()` cannot kill the slide).
    2. `LatestPosition.arrived()` transitions to `ArrivalPosition` when the reader was already
       following the tail (`awaits_source_advance=True`), while an explicit End jump
       (`awaits_source_advance=False`) keeps landing at the newest row."""
    from contextlib import contextmanager
    from types import SimpleNamespace
    from toad.client.history_pager import ReaderPlacement
    from toad.client.reader_position import ArrivalPosition, LatestPosition

    placed_calls = 0

    class _Pos:
        def laid_out(self, _w) -> bool:
            return True

        def place(self, _w) -> bool:
            nonlocal placed_calls
            placed_calls += 1
            return True

        def placed(self, _w, _reached: bool):
            return self

    class _Win(ReaderPlacement):
        def __init__(self, gliding: bool) -> None:
            self.follows_tail = True
            self._gliding = gliding
            self.reader_position = _Pos()
            self.scroll_y = 100.0

        def gliding_to_end(self) -> bool:
            return self._gliding

        @contextmanager
        def layout_scroll(self):
            yield

    # Active glide: place_reader() must defer to the glide instead of snapping scroll_y.
    gliding_win = _Win(gliding=True)
    assert gliding_win.place_reader() is False
    assert placed_calls == 0

    # Idle reader: place_reader() places normally.
    idle_win = _Win(gliding=False)
    assert idle_win.place_reader() is False
    assert placed_calls == 1

    # LatestPosition.arrived(): already-following replacement -> ArrivalPosition; End jump -> self.
    page = SimpleNamespace()
    following_latest = LatestPosition(revision=1, sources=(), awaits_source_advance=True)
    end_jump_latest = LatestPosition(revision=1, sources=(), awaits_source_advance=False)
    assert following_latest.arrived(page, ("k", 1)) == ArrivalPosition(page, ("k", 1))
    assert end_jump_latest.arrived(page, ("k", 1)) is end_jump_latest


def test_collapsed_tool_row_prepares_inline_without_worker_roundtrip(monkeypatch):
    """A collapsed tool row (`Summary`, `renders_inline=True`) prepares synchronously on the
    warm renderer inside `HistoryRowDelegate.styled_formatting` / `final_document_for` so a
    fast tool completion (`revision=0 -> 1`) never flashes plain text or changes height."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    import inspect
    from PySide6.QtGui import QFont
    from agent_comms.nominal.field_codec import ToolCallId
    from agent_comms.transcript.transcript_events import ToolStartTranscript
    from toad.acp.status import ToolCallStatus
    from toad.client.fragments import Shown
    from toad.markdown_links import LinkContext, ReferenceContext
    from toad.qt.agent_surface import QtLiveToolFragment
    from toad.qt.history import HistoryRowDelegate
    from toad.qt.window import RowPictures
    from acp import schema

    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())

    class _ExplodingPool:
        def submit(self, *_a, **_kw):
            raise AssertionError("collapsed tool row should prepare inline without worker pool")

    delegate = HistoryRowDelegate(renderer, RowPictures(1024 * 1024), _ExplodingPool())
    font = QFont("monospace", 10)
    try:
        for rev, status in ((0, "in_progress"), (1, "completed")):
            call = schema.ToolCall(tool_call_id="tc-inline", title="Read file", kind="read", status=status)
            ev = ToolStartTranscript(
                tool_call_id=ToolCallId("tc-inline"),
                tool_name="Read file",
                raw_input={},
                position=-1,
                timestamp=0.0,
            )
            frag = QtLiveToolFragment(
                events=(ev,),
                tool_call=ToolCallStatus.from_acp(call),
                output_parts=(),
                shown=Shown(),
                live_revision=rev,
            )
            doc = delegate.final_document_for(frag, font, 360)
            assert doc is not None
            assert delegate.is_prepared(delegate.fragment_key(frag, font, 360))
    finally:
        delegate.cleanup()


def test_pending_reader_scroll_flushes_before_layout_and_frame_paint_caches_per_frame(monkeypatch):
    """1. Scrolling off the tail and immediately triggering a layout (`show_rows` /
          `request_reader_layout`) before `_scroll_frame_timer` fires flushes
          `record_reader_scroll` first so `place_layout_reader` keeps the reader's new
          scroll offset (0 px jump) instead of snapping back to stale `TailPosition`,
          while `_scroll_frame` still runs `respond_to_scroll` and `prepare_viewport`.
       2. `HistoryRowDelegate.begin_paint` / `end_paint` resolves `_backing_image_format`
          once per frame across multiple painted rows instead of once per row."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    import inspect
    from contextlib import nullcontext
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter, QRegion, QTextDocument
    from toad.markdown_links import LinkContext, ReferenceContext
    from toad.qt.history import HistoryRowDelegate, QtHistoryWindow
    from toad.qt.virtual_scroll import NO_TAP_HIGHLIGHT
    from toad.qt.window import RowPictures

    # 1. Deferred scroll flush before layout prevents pre-scroll snap-back.
    calls: list[tuple[str, object]] = []
    win = QtHistoryWindow.__new__(QtHistoryWindow)
    win._restoring = False
    win._anchored = True
    win._reader_scrolled = False
    win._reader_position_dirty = False
    win._reader_moved = 0
    win._scrolled_to = 1000
    win._scroll_frame_pending = False
    win._scroll_frame_timer = MagicMock()
    win._prepare_timer = MagicMock()
    win._preparing = False
    win._vbar = MagicMock()
    win._vbar.value.return_value = 400
    win.tap_highlight = NO_TAP_HIGHLIGHT
    win.history_change = MagicMock(layout_requests=1)
    win._schedule_scroll_frame = lambda: calls.append(("schedule_frame", None))
    win.release_anchor = lambda: setattr(win, "_anchored", False)
    win.record_reader_scroll = lambda delta: calls.append(("record_scroll", delta))
    win.schedule_layout = lambda: calls.append(("schedule_layout", None))
    win.execute_layout = lambda: calls.append(("execute_layout", None))
    win.place_layout_reader = lambda: calls.append(("place_reader", None))
    win.repin_header = lambda: calls.append(("repin_header", None))
    win.respond_to_scroll = lambda val: calls.append(("respond_to_scroll", val))
    win.prepare_viewport = lambda: calls.append(("prepare_viewport", None))
    win.layout_scroll = lambda: nullcontext()
    monkeypatch.setattr(QtHistoryWindow, "at_end", property(lambda _self: False))

    # User scrolls up 600 px from 1000 -> 400; _scroll_frame has NOT fired yet.
    win.scrolled(400)
    assert win._reader_position_dirty is True
    assert win._reader_scrolled is True
    assert win._reader_moved == -600

    # Layout runs immediately (e.g. incoming wire arrival before 16 ms timer).
    win.request_reader_layout()
    assert ("record_scroll", -600) in calls
    assert calls.index(("record_scroll", -600)) < calls.index(("place_reader", None))
    assert win._reader_position_dirty is False
    assert win._reader_moved == 0
    # Deferred scroll frame still runs lookahead + viewport prep without double-recording delta.
    assert win._reader_scrolled is True
    win._scroll_frame()
    assert calls.count(("record_scroll", -600)) == 1
    assert ("respond_to_scroll", 400) in calls
    assert ("prepare_viewport", None) in calls

    # 2. begin_paint / end_paint resolves _backing_image_format once across rows in a frame.
    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())
    delegate = HistoryRowDelegate(renderer, RowPictures(4 * 1024 * 1024), MagicMock())
    doc = QTextDocument()
    doc.setPlainText("row")
    delegate.final_document_for = lambda _frag, _font, _w: doc
    format_calls = 0
    orig_format = delegate._backing_image_format

    def _counting_format(widget, painter):
        nonlocal format_calls
        format_calls += 1
        return orig_format(widget, painter)

    delegate._backing_image_format = _counting_format
    surface = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(surface)
    try:
        delegate.begin_paint(painter, QRect(0, 0, 200, 100), animating=False)
        assert delegate._frame_source_mode is True
        assert painter.compositionMode() == QPainter.CompositionMode.CompositionMode_Source
        for idx in range(4):
            frag = MagicMock(key=f"r{idx}", has_blocks=True, clipboard_text="row")
            assert delegate.paint_pictures(
                painter, frag, QRect(0, idx * 20, 200, 20), QRegion(QRect(0, 0, 200, 100))
            ) is True
        delegate.end_paint()
        assert format_calls == 1
        assert delegate._frame_paint is None
        assert delegate._frame_source_mode is False
    finally:
        painter.end()
        delegate.cleanup()

    # 3. QtFlash.show_flash resolves BackgroundColour without NameError.
    from toad.flash_host import ErrorTone
    from toad.qt.prompt_stack import QtFlash

    flash = QtFlash(MagicMock(), renderer)
    try:
        flash.show_flash("link unavailable", ErrorTone)
        assert flash.text() == "link unavailable"
        assert "background:" in flash.styleSheet()
    finally:
        flash.deleteLater()


def test_block_row_and_pinned_header_share_one_cached_document_and_prepare_inline(monkeypatch):
    """`HistoryRowDelegate.block_row` and `header_document` share one cache key via
    `Divider.standalone_cache_key` so crossing a message during scroll lays its header out
    once instead of twice, and `header_document` prepares a cold `Divider` inline without a
    worker-pool round-trip."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    import inspect
    from agent_comms.messaging.messages import InfoKind, Message
    from agent_comms.transcript.transcript_events import IncomingTranscript
    from PySide6.QtGui import QFont
    from toad.client.message_file_links import NO_PAGE_FILES
    from toad.client.transcript_fragments import transcript_fragments
    from toad.markdown_links import LinkContext, ReferenceContext
    from toad.qt.history import HistoryRowDelegate
    from toad.qt.transcript_fragments import QT_FRAGMENT_CLASSES
    from toad.qt.window import RowPictures

    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())

    class _ExplodingPool:
        def submit(self, *_a, **_kw):
            raise AssertionError("header_document should prepare inline Divider without worker pool")

    delegate = HistoryRowDelegate(renderer, RowPictures(4 * 1024 * 1024), _ExplodingPool())
    font = QFont("monospace", 10)
    try:
        msg = Message(sender="toad-qt", target="#comms", body="Body line 1\nBody line 2", type=InfoKind)
        frag = transcript_fragments(
            (IncomingTranscript.of(msg, reader="user"),),
            resolve_sent=lambda _r: {},
            classes=QT_FRAGMENT_CLASSES,
            files=NO_PAGE_FILES,
        )[0]
        header = frag.pinned_dividers[0]
        # 1. Cold header_document prepares inline without touching RenderProcessPool.
        cold_doc = delegate.header_document(header, font, 360)
        assert cold_doc is not None

        # 2. Prepared rows: block_row measures leading Gap + Divider and shares both:
        #    - header_document reuses the exact cached Divider doc (0 extra layouts),
        #    - a second message's block_row reuses the cached Gap doc (only 1 layout for its Divider).
        delegate._documents.clear()
        delegate._metrics.clear()
        msg2 = Message(sender="other", target="#comms", body="Second body", type=InfoKind)
        frag2 = transcript_fragments(
            (IncomingTranscript.of(msg2, reader="user"),),
            resolve_sent=lambda _r: {},
            classes=QT_FRAGMENT_CLASSES,
            files=NO_PAGE_FILES,
        )[0]
        for f in (frag, frag2):
            prep = delegate.row_preparation(f, font, 360)
            delegate._row_prepared(delegate.fragment_key(f, font, 360), prep.render())

        new_doc_calls = 0
        orig_new_document = delegate.new_document

        def _counting_new_doc(f, w):
            nonlocal new_doc_calls
            new_doc_calls += 1
            return orig_new_document(f, w)

        delegate.new_document = _counting_new_doc
        delegate.block_row(frag, font, 360, 40)
        assert new_doc_calls == 2  # Gap once + Divider 1 once
        pinned_doc = delegate.header_document(header, font, 360)
        assert pinned_doc is not None
        assert new_doc_calls == 2  # header_document hits the exact Divider doc from block_row
        delegate.block_row(frag2, font, 360, 40)
        assert new_doc_calls == 3  # Gap reused; only Divider 2 laid out
        assert delegate.header_document(frag2.pinned_dividers[0], font, 360) is not None
        assert new_doc_calls == 3
    finally:
        delegate.cleanup()


def test_observation_attach_rebinds_notification_views_across_resume_and_reconnect():
    from types import SimpleNamespace
    from weakref import WeakKeyDictionary
    from agent_comms.messaging.notification_reads import LiveNotificationRead
    from agent_comms.ui_model.observation import ObserveNotifications, ReadNotifications
    from toad.client.connection import FailedObservation, Observation, Observing
    from toad.client.subscribers import NotificationSubscriber

    class _View(NotificationSubscriber):
        def __init__(self) -> None:
            self.rebound = 0
            self.failed: list[Exception] = []

        def notifications_observed(self, outcomes) -> None:
            pass

        def notifications_failed(self, error: Exception) -> None:
            self.failed.append(error)

        def notifications_reload(self) -> None:
            pass

        def rebind_notifications(self) -> None:
            self.rebound += 1

    class _FakeObserving(Observing):
        root = Path("/tmp/fake-bus")

        def activate(self, access) -> None:
            pass

        @property
        def core(self):
            raise AssertionError("unused")

        def opened_selection(self):
            return None

        def user_identity(self, project):
            raise AssertionError("unused")

    access = SimpleNamespace(
        observation=None,
        sidebar_waiters=[],
        sidebar_views=(),
        revision=None,
        sidebar_interest=None,
        sidebar_current=None,
        team_interest=None,
        thread_status=MagicMock(),
        views_interest=None,
        notification_views=WeakKeyDictionary(),
        notification_known={},
        notification_interest=ObserveNotifications(frozenset()),
        events=MagicMock(),
    )

    obs1 = _FakeObserving(sidebar=MagicMock(), process=MagicMock(), access=access)
    obs2 = _FakeObserving(sidebar=MagicMock(), process=MagicMock(), access=access)
    failed = FailedObservation(RuntimeError("socket reset"), None, access=access)
    obs3 = _FakeObserving(sidebar=MagicMock(), process=MagicMock(), access=access)

    view_live = _View()
    view_closed = _View()
    read = ReadNotifications("/tmp/fake-bus", LiveNotificationRead(()))

    # 1. Android resume (Observing -> Observing) rebinds every active notification view.
    access.observation = obs2
    access.notification_views[view_live] = read
    access.notification_views[view_closed] = read
    obs2.attach(access, obs1)
    assert view_live.rebound == 1
    assert view_closed.rebound == 1
    assert len(access.notification_views) == 0

    # 2. Disconnect -> reconnect (Observing -> FailedObservation -> Observing) preserves
    #    live views and drops views closed during the outage.
    access.notification_views[view_live] = read
    access.notification_views[view_closed] = read
    access.observation = failed
    failed.attach(access, obs2)
    assert len(view_live.failed) == 1
    assert len(view_closed.failed) == 1
    failed.discard_notification_view(view_closed)

    access.observation = obs3
    obs3.attach(access, failed)
    assert view_live.rebound == 2
    assert view_closed.rebound == 1


def test_arrival_glide_and_layout_scroll_request_preparation():
    from toad.arrivals import AnimatesArrivals, ViewportArrival
    from toad.client.history_pager import ReaderPlacement
    from toad.client.reader_position import TAIL_ARRIVAL_TARGET

    class _Window(AnimatesArrivals, ReaderPlacement):
        def __init__(self) -> None:
            self._restoring = False
            self.scroll_y = 0.0
            self.scroll_target_y = 0.0
            self.tail_scroll_y = 240.0
            self.follows_tail = True
            self.lookahead = MagicMock()
            self.notification_checks = 0
            self.histories = (self,)
            self._clock = AnimationClock(lambda _interval: None)

        @property
        def animation_clock(self) -> AnimationClock:
            return self._clock

        @property
        def arrival_animation_visible(self) -> bool:
            return True

        def arrival_rows_height(self, keys):
            return 80.0

        def repaint_arrival_keys(self, keys) -> None:
            pass

        def check_visible_notifications(self) -> None:
            self.notification_checks += 1

    win = _Window()
    # Non-glide tail follow (`check_follow`) refreshes visible notifications once without
    # re-arming source page reads, while an older-page `layout_scroll` shift stays quiet.
    from toad.client.history_changes import NoHistoryChange
    with win.layout_scroll():
        win.scroll_y = 100.0
    assert win.notification_checks == 0
    assert NoHistoryChange().check_follow(win) is True
    assert win.scroll_y == 240.0
    assert win.notification_checks == 1

    # Mid-glide ticks must NOT spam notifications, while landing refreshes them once.
    win.scroll_y = 100.0
    arrival = ViewportArrival(win, ("row-1",))
    win.arrivals.append(arrival)
    arrival.attach_scroll(100.0, TAIL_ARRIVAL_TARGET, 240.0)
    win.glide = arrival
    arrival.apply_amount(0.5)
    assert win.notification_checks == 1
    arrival.land()
    assert win.scroll_y == 240.0
    assert win.notification_checks == 2


def test_qt_goal_bar_fit_document_uses_wrapped_height_for_width(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout
    from toad.qt.goal import QtGoalBar, WrappedText

    win = QWidget()
    win.resize(412, 915)
    bar = QWidget(win)
    bar.resize(412, 200)
    lay = QVBoxLayout(bar)
    lay.setContentsMargins(8, 4, 8, 4)
    doc = QScrollArea(bar)
    doc.setWidgetResizable(True)
    body = QWidget(doc)
    body_lay = QVBoxLayout(body)
    body_lay.setContentsMargins(0, 0, 0, 0)
    obj = WrappedText()
    obj.setText(
        "Objective: Ship Android/Qt Toad mobile UX fixes (IME adjustResize/safe-area, "
        "tab close, sidebar bands), profile & fix Pixel 8a scroll FPS with FrameProbe"
    )
    body_lay.addWidget(obj)
    body_lay.addStretch(1)
    doc.setWidget(body)
    lay.addWidget(doc)
    bar.document = doc
    bar.document_share = QtGoalBar.document_share
    try:
        win.show()
        app.processEvents()
        unwrapped_h = body.sizeHint().height()
        QtGoalBar.fit_document(bar)
        assert doc.height() > unwrapped_h
        assert doc.height() == min(
            body.heightForWidth(doc.viewport().width()),
            int(win.height() * QtGoalBar.document_share),
        )
    finally:
        win.deleteLater()


def test_header_pin_threshold_matches_block_row_without_laying_out_dividers(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])
    from dataclasses import dataclass
    from PySide6.QtGui import QFont
    from toad.client.line_blocks import Body, Divider, Gap, MutedRole, Span
    from toad.qt.history import HistoryRowDelegate, QtLineRenderer, RenderedRow
    from toad.qt.lines import DiffSettings, LinkContext

    class _EmptyRefs:
        def find(self, text):
            return ()

    class _View:
        def viewport_width(self):
            return 412

        def invalidate_row_height(self, row):
            pass

        def rows_changed(self):
            pass

        def rows_repainted(self):
            pass

    @dataclass(frozen=True)
    class _Frag:
        key: tuple
        shown: int
        revision: int
        line_blocks: tuple
        header_blocks: int
        pinned_dividers: tuple

        def sticky_header(self, block, row):
            return self.pinned_dividers if (block, row) > (self.header_blocks - 1, 0) else ()

    font = QFont("monospace", 10)
    renderer = QtLineRenderer(current_scheme(os.environ), LinkContext(Path("."), _EmptyRefs()), DiffSettings())
    width = 412
    frags = []
    for idx in range(5):
        divider = Divider((Span(f"sender-{idx} -> #comms · 10:0{idx}", MutedRole),), MutedRole)
        blocks = (Gap(), divider, Body(f"Message {idx}\nline 2"))
        frags.append(_Frag(("m", idx), 0, 0, blocks, 2, (divider,)))

    d_ref = HistoryRowDelegate(_View(), renderer, object())
    d_fast = HistoryRowDelegate(_View(), renderer, object())
    for frag in frags:
        leading = tuple(renderer.at_width(50).html((b,)) for b in frag.line_blocks[:3])
        row = RenderedRow(renderer.at_width(50).html(frag.line_blocks), leading, frag.pinned_dividers)
        d_ref._prepared[d_ref.fragment_key(frag, font, width)] = row
        d_fast._prepared[d_fast.fragment_key(frag, font, width)] = row

    for frag in frags:
        for y in range(0, 60, 3):
            blk, row_idx = d_ref.block_row(frag, font, width, y)
            expected = frag.sticky_header(blk, row_idx)
            threshold = d_fast.header_pin_threshold(frag, font, width)
            actual = frag.pinned_dividers if threshold is not None and y >= threshold else ()
            assert actual == expected
    # Only the single globally shared Gap block is ever laid out, never any Divider.
    assert len(d_fast._documents) == 1


def test_every_history_fragment_subclass_supports_retain_painted():
    """Every HistoryFragment painted by QtHistoryWindow (including tool, thinking, context,
    and live transcript fragments) must support retain_painted without crashing paintEvent."""
    import toad.qt.agent_surface
    import toad.qt.live_turn
    import toad.qt.transcript_fragments
    from toad.client.fragments import EvidencedFragment, HistoryFragment
    from toad.client.history import ReadMarkedHistory

    def walk(cls):
        out = set()
        for sub in cls.__subclasses__():
            out.add(sub)
            out.update(walk(sub))
        return out

    all_subclasses = walk(HistoryFragment)
    assert toad.qt.transcript_fragments.QtToolTranscriptFragment in all_subclasses
    assert toad.qt.transcript_fragments.QtThinkingTranscriptFragment in all_subclasses
    assert toad.qt.agent_surface.QtLiveToolFragment in all_subclasses
    assert toad.qt.live_turn.QtLiveFragment in all_subclasses

    missing = [c.__name__ for c in all_subclasses if not callable(getattr(c, "retain_painted", None))]
    assert not missing

    class _DummyOwner:
        def __init__(self):
            self._painted_reads = {}
            self.marked = 0

        def mark_visible_after_paint(self):
            self.marked += 1

    owner = _DummyOwner()
    non_evidenced = HistoryFragment(events=())
    ReadMarkedHistory.retain_painted(owner, non_evidenced)
    assert owner._painted_reads == {}
    assert owner.marked == 0
    assert "retain_painted" in EvidencedFragment.__dict__


def test_coalesced_loop_defers_drain_during_reentrant_process_events(monkeypatch):
    """Re-entrant QApplication.processEvents() inside an asyncio Task must defer
    CoalescedQEventLoop._drain_ready instead of stepping another Task and dropping its wakeup."""
    import asyncio
    from PySide6.QtCore import QEventLoop
    from toad.qt.client_start import CoalescedQEventLoop

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    loop = CoalescedQEventLoop(app)
    errors: list[dict] = []
    loop.set_exception_handler(lambda _loop, ctx: errors.append(ctx))
    try:
        async def drive() -> bool:
            sibling_done = False

            async def sibling() -> None:
                nonlocal sibling_done
                sibling_done = True

            task = asyncio.create_task(sibling())
            # Trigger Qt timer delivery synchronously while `drive` is still active on the stack.
            app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeSocketNotifiers)
            await task
            return sibling_done

        assert loop.run_until_complete(drive()) is True
        assert errors == []
    finally:
        loop.close()


def test_line_block_triggers_header_collapse_and_channel_row_tones():
    """Divider declares triggers_header_collapse=True (replacing isinstance checks in QtHistoryWindow),
    and ChannelRowFace.row_tones derives from ChannelRowTone.__subclasses__()."""
    from toad.client.line_blocks import Body, Divider, Gap, LineBlock, Summary
    from toad.client.theme_tones import (
        ChannelAlternateRowToneColour,
        ChannelRowTone,
        ChannelRowToneColour,
        SidebarToggleToneColour,
    )
    from toad.sidebar_rows import ChannelRowFace

    assert LineBlock.triggers_header_collapse is False
    assert Divider.triggers_header_collapse is True
    assert Summary.triggers_header_collapse is False
    assert Gap.triggers_header_collapse is False
    assert Body.triggers_header_collapse is False
    assert issubclass(ChannelRowToneColour, ChannelRowTone)
    assert issubclass(ChannelAlternateRowToneColour, ChannelRowTone)
    assert not issubclass(SidebarToggleToneColour, ChannelRowTone)
    assert ChannelRowFace.row_tones == (ChannelRowToneColour, ChannelAlternateRowToneColour)


def test_sticky_header_lru_caches_headers_and_opaque_scroll_clip_skips_occluded_strip(monkeypatch):
    """QtStickyHeader keeps recently pinned QTextDocuments and rasterized QImages in bounded
    LRUs across header switches and skips no-op resize/move calls; VirtualRowCanvas.scrollContentsBy
    subtracts WA_OpaquePaintEvent covers from viewport.update(dirty)."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    from collections import OrderedDict
    from PySide6.QtCore import QPoint, QRect, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QTextDocument
    from PySide6.QtWidgets import QWidget
    from toad.client.line_blocks import Divider, MutedRole, Span
    from toad.qt.history import QtStickyHeader
    from toad.qt.virtual_scroll import VirtualRowCanvas

    # 1. QtStickyHeader LRU + no-op geometry guard.
    class _FakeHistoryWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.resize(412, 600)
            self._vp = QWidget(self)
            self._vp.setGeometry(0, 0, 412, 600)
            self.rows = MagicMock()
            self.rows.links_revision = 1
            self.rows.renderer = object()
            self.rows._theme_colours.return_value = ("#111111", QColor("#111111"), QColor("#eeeeee"))
            self.tap_highlight = MagicMock()
            self.tap_highlight.is_pinned.return_value = False

        def viewport(self) -> QWidget:
            return self._vp

    host = _FakeHistoryWindow()
    build_calls: list[Divider] = []

    def make_doc(header: Divider, _font, width: int) -> QTextDocument:
        build_calls.append(header)
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setTextWidth(width)
        doc.setPlainText(header.spans[0].text)
        return doc

    host.rows.header_document.side_effect = make_doc
    sticky = QtStickyHeader(host)

    h1 = Divider((Span("Header A"),), MutedRole)
    h2 = Divider((Span("Header B"),), MutedRole)
    resize_calls = 0
    move_calls = 0
    orig_resize, orig_move = sticky.resize, sticky.move

    def counted_resize(*args):
        nonlocal resize_calls
        resize_calls += 1
        return orig_resize(*args)

    def counted_move(*args):
        nonlocal move_calls
        move_calls += 1
        return orig_move(*args)

    sticky.resize = counted_resize
    sticky.move = counted_move

    sticky.draw_pinned((h1,), 0, 412)
    sticky.show()
    # Paint h1 so its QImage lands in _pixmap_cache.
    sticky.grab()
    sticky.draw_pinned((h2,), 0, 412)
    sticky.grab()
    # Switch back to h1: must hit both laid_out and _pixmap_cache with 0 new builds and 0 resizes/moves.
    sticky.draw_pinned((h1,), 0, 412)
    sticky.grab()
    assert build_calls == [h1, h2]
    assert len(sticky.laid_out) == 2
    assert len(sticky._pixmap_cache) == 2
    assert resize_calls == 1
    assert move_calls == 0
    sticky.draw_pinned((h1,), 4, 412)
    assert move_calls == 1

    # 2. VirtualRowCanvas.scrollContentsBy excludes full-width WA_OpaquePaintEvent cover from dirty update.
    canvas = VirtualRowCanvas(MagicMock())
    canvas.resize(412, 600)
    canvas.show()
    vp_geo = canvas.viewport().geometry()
    opaque_top = QWidget(canvas)
    opaque_top.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
    opaque_top.setGeometry(vp_geo.left(), vp_geo.top(), vp_geo.width(), 24)
    opaque_top.show()

    updates: list[QRect] = []
    orig_update = canvas.viewport().update

    def capture_update(region):
        updates.append(region.boundingRect() if hasattr(region, "boundingRect") else region)
        return orig_update(region)

    canvas.viewport().update = capture_update
    canvas.scrollContentsBy(0, -40)
    assert updates == [], f"opaque full-width header must not trigger extra viewport.update, got {updates}"

    # Adding a translucent cover still updates the non-occluded band around it.
    translucent_bottom = QWidget(canvas)
    translucent_bottom.setGeometry(vp_geo.left() + 140, vp_geo.top() + vp_geo.height() - 40, 120, 32)
    translucent_bottom.show()
    canvas.scrollContentsBy(0, -40)
    assert len(updates) == 1
    assert updates[0].top() == vp_geo.height() - 40
    assert updates[0].top() > 24, "opaque top band must stay excluded from dirty region"

    # A mid-viewport full-width opaque cover does NOT satisfy clear+cover == vp_rect:
    # the uncovered band on the opposite side must still be updated.
    translucent_bottom.hide()
    opaque_top.setGeometry(vp_geo.left(), vp_geo.top() + 100, vp_geo.width(), 24)
    updates.clear()
    canvas.scrollContentsBy(0, -40)
    assert len(updates) == 1
    assert updates[0].top() == 0 and updates[0].bottom() == 99

    # 3. QtHistoryWindow.floating_covers avoids self.children() and splits opaque covers.
    fake_win = MagicMock()
    fake_win._viewport = canvas.viewport()
    fake_win.sticky_header = opaque_top
    fake_win.jump_bar = translucent_bottom
    fake_win.children.side_effect = AssertionError("QtHistoryWindow.floating_covers must not call self.children()")
    opaque_top.setGeometry(vp_geo.left(), vp_geo.top(), vp_geo.width(), 24)
    covers, opaque = QtHistoryWindow.floating_covers(fake_win)
    assert len(covers) == 1 and opaque == covers

    # 4. RowPictures popitem(last=False) eviction keeps exact byte accounting.
    pics = RowPictures(limit=200 * 4)
    img1 = QImage(10, 10, QImage.Format.Format_RGB32)
    img2 = QImage(10, 10, QImage.Format.Format_RGB32)
    img3 = QImage(10, 10, QImage.Format.Format_RGB32)
    pics.keep("a", (1,), None, img1)
    pics.keep("b", (1,), None, img2)
    assert pics.bytes == 200 * 4
    pics.keep("c", (1,), None, img3)
    assert list(pics.rows.keys()) == ["b", "c"]
    assert pics.bytes == 200 * 4
    pics.drop("b")
    assert pics.bytes == 100 * 4

    # 5. HistoryRowDelegate.begin_paint resolves font_spec & layout_width once per frame,
    # so steady-state paint_pictures hits _documents directly without per-row _font_spec calls.
    renderer = QtLineRenderer(current_scheme(os.environ), LinkContext(Path("."), frozenset()), DiffSettings())
    del_pics = RowPictures(4 * 1024 * 1024)
    delegate = HistoryRowDelegate(renderer, del_pics, MagicMock())
    delegate.view = MagicMock(has_active_arrivals=False)
    delegate.view.backing_device.return_value = canvas
    delegate.view.viewport_width.return_value = 300
    delegate.view.tap_highlight.matches_row.return_value = False
    frag = MagicMock(has_blocks=True, key="f1", shown=True, revision=1)
    doc = QTextDocument()
    doc.setPlainText("hello")
    doc.setTextWidth(300)
    prep_key = delegate.preparation_key_for(frag, canvas.font(), 300)
    delegate._documents[(prep_key, 300)] = doc
    frame_img = QImage(300, 120, QImage.Format.Format_ARGB32_Premultiplied)
    font_spec_calls = 0
    orig_font_spec = delegate._font_spec

    def counting_font_spec(f):
        nonlocal font_spec_calls
        font_spec_calls += 1
        return orig_font_spec(f)

    delegate._font_spec = counting_font_spec  # type: ignore[method-assign]
    p = QPainter(frame_img)
    delegate.begin_paint(p, QRect(0, 0, 300, 120))
    for _ in range(5):
        assert delegate.paint_pictures(p, frag, QRect(0, 0, 300, 40), None)
    delegate.end_paint()
    p.end()
    assert font_spec_calls == 1, f"expected 1 _font_spec call per frame, got {font_spec_calls}"
    host.close()
    canvas.close()


def test_sidebar_tone_batching_scroll_cover_cache_and_cached_notification_references(monkeypatch):
    """ConversationRows.batching_row_tones paints O(N) once and skips unchanged brushes;
    VirtualRowCanvas.scrollContentsBy caches uncovered/dirty regions for steady covers;
    WireMessage.notification_references caches per fragment instead of re-minting on every check."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])

    # 1. ConversationRows.batching_row_tones coalesces N inserts/reorders into 1 pass and skips unchanged tones.
    bg_calls = 0

    class _ToneItem(SidebarItem, QTreeWidgetItem):
        def __init__(self, key: str) -> None:
            super().__init__()
            self.key = key

        def setBackground(self, column: int, brush: QBrush) -> None:  # type: ignore[override]
            nonlocal bg_calls
            bg_calls += 1
            super().setBackground(column, brush)

    class _FakeTree(QTreeWidget):
        def __init__(self) -> None:
            super().__init__()
            self._tone_brushes: dict[object, QBrush] = {}
            self._tone_batch_depth = 0
            self._dirty_tone_parents: dict[int, tuple[QTreeWidgetItem, int]] = {}
            self.model().rowsInserted.connect(self._paint_row_tones_from)
            self.model().rowsRemoved.connect(self._paint_row_tones_from)

        def _row_tone_brush(self, tone):
            brush = self._tone_brushes.get(tone)
            if brush is None:
                brush = self._tone_brushes[tone] = QBrush(QColor("#222222" if tone is SidebarItem.row_tones[0] else "#333333"))
            return brush

    _FakeTree.batching_row_tones = ConversationRows.batching_row_tones
    _FakeTree._paint_children_tones = ConversationRows._paint_children_tones
    _FakeTree._paint_row_tones_from = ConversationRows._paint_row_tones_from

    tree = _FakeTree()
    root = tree.invisibleRootItem()
    items = [_ToneItem(f"row-{i}") for i in range(20)]
    with tree.batching_row_tones():
        for idx, item in enumerate(items):
            root.insertChild(idx, item)
    # Exactly 1 setBackground per row (20, not 20*21/2 = 210).
    assert bg_calls == 20
    # Re-running with identical parity does 0 setBackground calls.
    tree._paint_children_tones(root, 0)
    assert bg_calls == 20
    # Swapping two even-indexed items leaves every parity unchanged -> 0 setBackground calls.
    with tree.batching_row_tones():
        taken = root.takeChild(2)
        root.insertChild(2, taken)
    assert bg_calls == 20
    tree.close()

    # 2. VirtualRowCanvas.scrollContentsBy reuses cached (clear, dirty) when covers don't move.
    canvas = VirtualRowCanvas(MagicMock())
    canvas.resize(412, 600)
    canvas.show()
    vp_geo = canvas.viewport().geometry()
    cover = QWidget(canvas)
    cover.setGeometry(vp_geo.left() + 140, vp_geo.top() + vp_geo.height() - 40, 120, 32)
    cover.show()
    uncovered_calls = 0
    orig_uncovered = VirtualRowCanvas.uncovered

    def counting_uncovered(rect, covers):
        nonlocal uncovered_calls
        uncovered_calls += 1
        return orig_uncovered(rect, covers)

    monkeypatch.setattr(VirtualRowCanvas, "uncovered", staticmethod(counting_uncovered))
    for _ in range(5):
        canvas.scrollContentsBy(0, -40)
    assert uncovered_calls == 1, f"expected 1 uncovered() call for steady covers, got {uncovered_calls}"
    # Moving the cover invalidates the cache and recomputes once.
    cover.setGeometry(vp_geo.left() + 100, vp_geo.top() + vp_geo.height() - 40, 120, 32)
    canvas.scrollContentsBy(0, -40)
    assert uncovered_calls == 2
    canvas.close()

    # 3. WireMessage.notification_references caches per fragment.
    ref_calls = 0

    class _FakeRole:
        def notification_references(self, _message):
            nonlocal ref_calls
            ref_calls += 1
            return ("ref-1",)

    frag = object.__new__(WireMessage)
    frag.events = (SimpleNamespace(message=SimpleNamespace(role=_FakeRole())),)
    assert frag.notification_references == ("ref-1",)
    assert frag.notification_references == ("ref-1",)
    assert ref_calls == 1
