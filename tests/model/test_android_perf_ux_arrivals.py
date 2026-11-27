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
        assert delegate.paint_pictures(painter, fake_frag, rect, clip_region, None) is True
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

        # Tap on outer divider rule (x=2) -> PinnedHeaderTapHighlight + toggle_collapse.
        fake_win._set_tap_highlight.reset_mock()
        assert sticky.handle_tap(QPoint(2, py)) is True
        assert isinstance(fake_win._set_tap_highlight.call_args[0][0], PinnedHeaderTapHighlight)
        fake_win.toggle_collapse.assert_called_with(frag.collapse_link)
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
            painter, fake_frag, QRect(0, 0, 200, 40), QRegion(QRect(0, 0, 200, 100)), None
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
    clock = AnimationClock(lambda _interval: None)
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
