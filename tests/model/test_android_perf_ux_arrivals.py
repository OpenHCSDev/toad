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
    composer._buttons_band_size.return_value = (0, 0)
    composer._needs_button_clearance.return_value = False

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
    scroller_owner.deleteLater()
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
    clock = QtAnimationClock(lambda _interval: None)
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
    """`QListView::paintEvent` leaves `painter.hasClipping()` False; `QtHistoryWindow.paintEvent`
    captures `event.region()` so `HistoryRowDelegate.paint_pictures` rasterizes only visible
    tiles vertically and horizontally instead of blowing the 64 MB `RowPictures` cache."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    import inspect
    from PySide6.QtCore import QModelIndex, QRect, QSize
    from PySide6.QtGui import QFont, QPainter, QPixmap, QRegion, QTextDocument
    from PySide6.QtWidgets import QStyleOptionViewItem
    from toad.markdown_links import ReferenceContext
    from toad.qt.history import HistoryRowDelegate, RowPictures

    scheme = current_scheme(os.environ)
    concrete = [c for c in ReferenceContext.__subclasses__() if not inspect.isabstract(c)][0]
    renderer = QtLineRenderer(scheme, LinkContext(Path("."), concrete()), DiffSettings())
    pictures = RowPictures(64 * 1024 * 1024)
    delegate = HistoryRowDelegate(renderer, pictures, MagicMock())

    # Tall (2560 px) + wide (1800 px) row painted into a 400x300 viewport with paintEvent region.
    doc = QTextDocument()
    doc.setPlainText("line\n" * 120)
    delegate.painted_document = lambda _idx, _opt: doc

    viewport = MagicMock()
    viewport.rect.return_value = QRect(0, 0, 400, 300)
    view = MagicMock()
    view.viewport.return_value = viewport
    view._paint_region = QRegion(QRect(0, 0, 400, 300))
    delegate.view = view

    surface = QPixmap(400, 300)
    painter = QPainter(surface)
    assert painter.hasClipping() is False  # exact QListView::paintEvent condition
    option = QStyleOptionViewItem()
    option.rect = QRect(0, -1000, 1800, 2560)
    option.font = QFont()

    # Track tiles rasterized.
    painted_tiles: list[tuple[int, int, int, int]] = []
    orig_paint = delegate._paint_tile_document

    def record_paint(drawing, local, index, document, left, top, width, height):
        painted_tiles.append((left, top, width, height))
        orig_paint(drawing, local, index, document, left, top, width, height)

    delegate._paint_tile_document = record_paint
    try:
        assert delegate.paint_pictures(painter, option, QModelIndex(), "row-1", None) is True
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


def test_composer_floating_buttons_and_nav_separators_and_ime_inset_file(monkeypatch, tmp_path) -> None:
    """Floating composer buttons sit inside `self.frame` (not `editor_row`), reserve bottom
    clearance only when the last line collides or scrolls, `_NavSeparator` draws a 1 px
    divider, and `QtToadApp.fit_safe_area` honors `TOAD_IME_INSET_FILE` across stale
    `QtWindow.onLayoutChange` reads."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    from PySide6.QtCore import QMargins
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QPlainTextEdit, QPushButton
    from toad.qt.composer import Composer
    from toad.qt.window import QtToadApp

    # 1. Floating box buttons + collision clearance logic.
    frame = QFrame()
    frame.resize(300, 80)
    layout = QHBoxLayout(frame)
    editor = QPlainTextEdit(frame)
    editor.resize(280, 40)
    layout.addWidget(editor)

    send_btn = QPushButton("➤")
    attach_btn = QPushButton("+")
    composer = MagicMock(spec=Composer)
    composer.frame = frame
    composer.editor_row = layout
    composer.editor = editor
    composer.box_buttons = ()
    composer.font.return_value = frame.font()
    composer.fontMetrics.return_value = frame.fontMetrics()
    composer.document_margin.return_value = 4
    composer._visible_box_buttons = lambda: Composer._visible_box_buttons(composer)
    composer._buttons_band_size = lambda: Composer._buttons_band_size(composer)
    composer._place_box_buttons = lambda: Composer._place_box_buttons(composer)
    composer.fit_buttons = lambda: Composer.fit_buttons(composer)
    composer.fit_height = lambda: None

    Composer.add_box_button(composer, send_btn)
    Composer.add_box_button(composer, attach_btn)
    assert composer.box_buttons == (attach_btn, send_btn)
    # Buttons are children of `frame`, NOT packed into `editor_row`.
    assert layout.indexOf(send_btn) == -1
    assert layout.indexOf(attach_btn) == -1
    assert send_btn.parentWidget() is frame and attach_btn.parentWidget() is frame

    # Empty, short 1-line, or multiline text whose last visual line fits left of `+` / `➤`
    # needs no extra clearance row; scrolled or colliding last lines reserve the button band.
    composer.text = ""
    assert Composer._needs_button_clearance(composer, 1, 1) is False
    composer.text = "hi"
    editor.setPlainText("hi")
    assert Composer._needs_button_clearance(composer, 1, 1) is False
    assert Composer._needs_button_clearance(composer, 2, 2) is False
    assert Composer._needs_button_clearance(composer, 5, 3) is True
    long_line = "x" * 120
    composer.text = long_line
    editor.setPlainText(long_line)
    assert Composer._needs_button_clearance(composer, 1, 1) is True
    assert Composer._needs_button_clearance(composer, 2, 2) is True

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


def test_parallel_render_and_hold_touch_link_priority_and_live_tap_flash(monkeypatch, tmp_path) -> None:
    """Covers parallel 2-worker `HoldsRows.render_and_hold`, header name tap priority over
    collapse within touch slop, row-tracked tap highlight, and IME Back-close resync."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    import asyncio
    import inspect
    from PySide6.QtCore import QMargins, QPoint, QRect
    from PySide6.QtGui import QTextDocument
    from agent_comms.messaging.messages import InfoKind, Message
    from agent_comms.transcript.transcript_events import IncomingTranscript
    from toad.client.line_blocks import OpenTarget
    from toad.client.message_file_links import NO_PAGE_FILES
    from toad.client.prepared_pages import HoldsRows
    from toad.client.transcript_fragments import transcript_fragments
    from toad.markdown_links import ReferenceContext
    from toad.qt.history import QtHistoryWindow
    from toad.qt.transcript_fragments import QT_FRAGMENT_CLASSES
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
    #    rather than collapsing the message.
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
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setTextWidth(360)
    doc.setHtml(renderer.html(frag.line_blocks))
    layout = doc.documentLayout()

    # Locate the exact bounding box of the `toad-qt` link in the rendered header.
    sender_pts = [
        (x, y)
        for y in range(0, 60)
        for x in range(0, 360, 2)
        if "toad-qt" in layout.anchorAt(QPoint(x, y))
    ]
    assert sender_pts
    mid_x = (min(x for x, _ in sender_pts) + max(x for x, _ in sender_pts)) // 2
    just_below_y = max(y for _, y in sender_pts) + 4  # outside exact glyph box, within touch slop

    fake_win = MagicMock()
    fake_index = MagicMock()
    fake_index.isValid.return_value = True
    fake_win.indexAt.return_value = fake_index
    fake_win.visualRect.return_value = QRect(0, 0, 360, int(doc.size().height()))
    fake_win.rows.layout_width.return_value = 360
    fake_win.rows.row_document.return_value = doc
    fake_win._TOUCH_LINK_OFFSETS = QtHistoryWindow._TOUCH_LINK_OFFSETS
    picked = QtHistoryWindow._tapped_link_at(fake_win, QPoint(mid_x, just_below_y))
    assert picked == OpenTarget("toad-qt")

    # 3. Tap highlight tracks live row geometry rather than freezing at stale pixels.
    fake_win.widget_gone = False
    fake_win._tap_flash = (frag.key, 10, 20)
    fake_win.model_rows.row_of.return_value = 0
    fake_win.viewport.return_value.rect.return_value = QRect(0, 0, 360, 600)
    fake_win.visualRect.return_value = QRect(0, 120, 360, 80)
    assert QtHistoryWindow._live_tap_flash_rect(fake_win) == QRect(0, 130, 360, 20)
    fake_win.visualRect.return_value = QRect(0, 40, 360, 50)
    assert QtHistoryWindow._live_tap_flash_rect(fake_win) == QRect(0, 50, 360, 20)

    # 4. QtToadApp._resync_safe_area restores resting bottom margin after IME file hits 0
    #    even when Qt deduplicates safeAreaMarginsChanged.
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
    fake_app.windowHandle.return_value.safeAreaMargins.return_value = QMargins(0, 48, 0, 24)
    fake_app.fit_safe_area = lambda m: QtToadApp.fit_safe_area(fake_app, m)
    QtToadApp._resync_safe_area(fake_app)
    assert fake_app._safe_area_resync_pending is False
    assert fake_app.setContentsMargins.call_args[0][0].bottom() == 24
    assert fake_app._keyboard_open is False
