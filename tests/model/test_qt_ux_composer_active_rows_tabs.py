"""Regression tests for Qt/TUI UX fixes (#comms 11984):
1. Qt `_qt_sequences` maps `enter`, `ctrl+enter`, and `shift+enter` to both `Return`
   (main keyboard) and `Enter` (numpad) so Enter/Ctrl+Enter send and Shift+Enter inserts newline.
2. Qt `Composer.dismiss_control` exits Vim Insert -> Normal and Normal -> history focus
   without clearing the draft.
3. Qt `QtNameWaveDelegate.paint` paints active (waving) sidebar rows with their alternating
   `BackgroundRole` tone brush (matching idle rows) and invalidates cached row images when
   the row's alternating tone changes.
4. `WireMessageStyle.body` strips leading blank lines between the message header and first
   non-whitespace line while preserving indentation; `RowDocuments.PREFORMATTED_SHEET`
   suppresses Qt's 12 px default `<p>` top margin.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import shiboken6
from PySide6.QtCore import QEvent, QMimeData, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QKeyEvent, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem, QWidget
from pyqt_reactive.widgets.shared.list_item_delegate import LAYOUT_ROLE
from pyqt_reactive.widgets.shared.styled_text_layout import Segment, StyledTextLayout

from toad.client.input_modality import KeyboardInput, TouchInput
from toad.client.message_files import MessagePromptComposer
from toad.client.prompt_composer import PromptComposer
from toad.client.sidebar_filter import SidebarFilter, SidebarSearchField
from toad.client.theme_tones import InputPlaceholderToneColour, ScrollbarTones, SidebarToggleToneColour
from toad.key_modes import Standard, VimInsert, VimNormal
from toad.markdown_links import LinkContext
from toad.message_rows import IrcMessageStyle, MarkdownMessageStyle
from toad.neovim_editing import HostsNeovim
from toad.patch import DiffSettings
from toad.prompt_actions import PasteClipboardAction
from toad.qt.action_shortcuts import _qt_sequences
from toad.qt.composer import Composer, ComposerEditor, QtMessageComposer, _qt_key_to_input
from toad.qt.history import HistoryRowDelegate
from toad.qt.lines import QtLineRenderer
from toad.qt.name_wave import PaintedRowTone, QtNameWaveDelegate, QtSessionTabBar
from toad.qt.prompt_stack import QtEditingModeBadge
from toad.qt.side_bar import QtSideBar, QtSideBarToggle
from toad.qt.sidebar_panel import QtSidebarSearch
from toad.qt.window import _scrollbar_qss
from toad.sidebar_layout import SidebarLayout, SidebarSurface, SidebarToggleFace
from toad.sidebar_placement import ChannelsSidebarPlacement
from toad.terminal_origin import TerminalOrigin
from toad.widgets.side_bar import SideBar, SideBarToggle, SidebarSearch
from ui_theme.catalog import SCHEMES
from ui_theme.scheme import BlockCursorBackgroundColour, BlockCursorForegroundColour, PrimaryColour


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_qt_sequences_expand_enter_to_return_and_enter() -> None:
    assert [s.toString() for s in _qt_sequences("enter")] == ["Return", "Enter"]
    assert [s.toString() for s in _qt_sequences("ctrl+enter")] == ["Ctrl+Return", "Ctrl+Enter"]
    assert [s.toString() for s in _qt_sequences("shift+enter")] == ["Shift+Return", "Shift+Enter"]
    assert [s.toString() for s in _qt_sequences("ctrl+plus")] == ["Ctrl++", "Ctrl+Shift+="]
    assert [s.toString() for s in _qt_sequences("ctrl+=")] == ["Ctrl+="]
    assert [s.toString() for s in _qt_sequences("ctrl+-")] == ["Ctrl+-"]
    assert [s.toString() for s in _qt_sequences("ctrl+0")] == ["Ctrl+0"]
    assert [s.toString() for s in _qt_sequences("G")] == ["Shift+G"]
    assert [s.toString() for s in _qt_sequences("escape")] == ["Esc"]


def test_qt_composer_dismiss_control_dispatches_to_editing_mode() -> None:
    dismissed: list[object] = []
    hidden_offers: list[tuple] = []

    composer = Composer.__new__(Composer)
    composer.offers = SimpleNamespace(
        isVisible=lambda: False,
        show_offers=lambda title, offers: hidden_offers.append((title, offers)),
    )
    editor = SimpleNamespace(
        editing_mode=SimpleNamespace(dismiss_input=lambda ed: dismissed.append(ed)),
        toPlainText=lambda: "draft",
    )
    composer.editor = editor

    # With offers hidden, Escape dispatches polymorphically to `editing_mode.dismiss_input(editor)`
    # (in real Neovim that queues `<Esc>`, exiting Insert/Visual -> Normal and idle Normal -> history).
    composer.dismiss_control()
    assert dismissed == [editor]
    assert hidden_offers == []

    # With offers visible, Escape hides offers without touching the editing engine.
    composer.offers = SimpleNamespace(
        isVisible=lambda: True,
        show_offers=lambda title, offers: hidden_offers.append((title, offers)),
    )
    composer.dismiss_control()
    assert dismissed == [editor]
    assert hidden_offers == [("", ())]


def test_qt_active_waving_row_matches_alternating_background_tone() -> None:
    _app()
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.resize(260, 120)
    delegate = QtNameWaveDelegate(
        QColor("#ff9900"),
        QColor("#ffffff"),
        QColor("#aaaaaa"),
        QColor("#ffffff"),
        tree,
    )
    tree.setItemDelegateForColumn(0, delegate)

    odd_color = QColor("#2a3b4c")
    even_color = QColor("#182028")

    class _PaintedItem(PaintedRowTone, QTreeWidgetItem):
        pass

    item = _PaintedItem(tree)
    item.setData(0, LAYOUT_ROLE, StyledTextLayout(name=Segment("comms-a"), detail_line="Working", multiline=True))
    item.setBackground(0, QBrush(odd_color))
    item._painted_rgba = odd_color.rgba()
    item.animation = object()
    item.painted_span = (0, 3)

    index = tree.indexFromItem(item, 0)

    def _paint_corner(target_item) -> QColor:
        image = QImage(240, 44, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#000000"))
        painter = QPainter(image)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 240, 44)
        opt.widget = tree
        delegate.paint(painter, opt, index)
        painter.end()
        return image.pixelColor(230, 38)

    # First paint warms `bold` cache; second paint (with shifted wave span) hits the active-wave fast path!
    cold_bg = _paint_corner(item)
    item.painted_span = (1, 4)
    fast_path_bg = _paint_corner(item)
    assert cold_bg == odd_color
    assert fast_path_bg == odd_color

    # Changing the item's alternating tone (e.g. sibling inserted above) must invalidate cache and paint new tone!
    item.setBackground(0, QBrush(even_color))
    item._painted_rgba = even_color.rgba()
    shifted_bg = _paint_corner(item)
    assert shifted_bg == even_color


def test_wire_message_style_strips_leading_blank_lines_and_qt_sheet_zeros_top_margin() -> None:
    fake_row = SimpleNamespace()
    for style in (MarkdownMessageStyle(), IrcMessageStyle()):
        blocks = style.body(fake_row, "\n\n   \n    indented first line\n\nsecond")
        assert len(blocks) == 1
        assert blocks[0].text == "    indented first line\n\nsecond"

    assert "margin-top: 0px" in HistoryRowDelegate.PREFORMATTED_SHEET


def test_qt_editing_mode_badge_shows_standard_after_leaving_vim_normal() -> None:
    _app()
    renderer = QtLineRenderer(SCHEMES[0], LinkContext(None, ()), DiffSettings())
    synced: list[bool] = []
    info_bar = SimpleNamespace(sync_visibility=lambda: synced.append(True))
    badge = QtEditingModeBadge(renderer, info_bar)

    vim_normal = VimNormal()
    badge.present_editing_mode(vim_normal, focused=True)
    assert badge.text() == vim_normal.label
    assert not badge.isHidden()

    # Escaping out of Vim NORMAL unfocuses the editor: badge must show STANDARD, not hide!
    badge.present_editing_mode(vim_normal, focused=False)
    assert badge.text() == "STANDARD"
    assert not badge.isHidden()

    # Non-vim Standard mode keeps the badge hidden.
    badge.present_editing_mode(Standard(), focused=False)
    assert badge.text() == ""
    assert badge.isHidden()


def test_scrollbar_tones_match_textual_color_system_and_qt_qss() -> None:
    from agent_comms.nominal.field_codec import FieldCodec
    from textual.theme import Theme

    scheme = SCHEMES[0]
    renderer = QtLineRenderer(scheme, LinkContext(None, ()), DiffSettings())
    colours = {m.name: v.hex for m, v in scheme.colours.items()}
    variables = {m.name: v.hex for m, v in scheme.resolved_elements.items()}
    textual_vars = FieldCodec.decode(
        Theme,
        {
            "name": scheme.name,
            "dark": scheme.dark,
            "ansi": scheme.from_terminal,
            "variables": variables,
            **colours,
        },
    ).to_color_system().generate()

    assert renderer.theme(ScrollbarTones.track_colour).lower() == textual_vars["scrollbar-background"].lower()
    assert renderer.theme(ScrollbarTones.thumb_colour).lower() == textual_vars["scrollbar"].lower()
    assert renderer.theme(ScrollbarTones.hover_colour).lower() == textual_vars["scrollbar-hover"].lower()
    assert renderer.theme(ScrollbarTones.active_colour).lower() == textual_vars["scrollbar-active"].lower()

    qss = _scrollbar_qss(renderer)
    assert renderer.theme(ScrollbarTones.track_colour) in qss
    assert renderer.theme(ScrollbarTones.thumb_colour) in qss
    assert renderer.theme(ScrollbarTones.hover_colour) in qss
    assert renderer.theme(ScrollbarTones.active_colour) in qss
    assert "::add-page:horizontal" in qss
    assert KeyboardInput.tab_scrollbar_cells == 1
    assert TouchInput.tab_scrollbar_cells == 0


def test_sidebar_bars_and_search_inherit_shared_theme_roles_across_textual_and_qt() -> None:
    _app()
    scheme = SCHEMES[0]
    renderer = QtLineRenderer(scheme, LinkContext(None, ()), DiffSettings())

    # Shared inheritance: both Textual and Qt inherit the exact same colour declarations.
    assert issubclass(SideBar, SidebarSurface) and issubclass(QtSideBar, SidebarSurface)
    assert SideBar.tone is SidebarSurface.tone is QtSideBar.tone
    assert issubclass(SideBarToggle, SidebarToggleFace) and issubclass(QtSideBarToggle, SidebarToggleFace)
    assert SideBarToggle.highlight_background is SidebarToggleFace.hover_background_colour is BlockCursorBackgroundColour
    assert SideBarToggle.highlight_foreground is SidebarToggleFace.hover_foreground_colour is BlockCursorForegroundColour
    assert issubclass(SidebarSearch, SidebarSearchField) and issubclass(QtSidebarSearch, SidebarSearchField)

    # QtSideBar.paint_theme does NOT clobber QtSideBarToggle with `#SidebarPane > QWidget`.
    host = QWidget()
    layout = SidebarLayout(
        SimpleNamespace(current_terminals=lambda: (), store_terminals=lambda _t: None),
        TerminalOrigin(),
    )
    side = QtSideBar(
        layout,
        ChannelsSidebarPlacement,
        QWidget(host),
        heading=lambda: "All",
        laid_out=lambda: None,
        client=SimpleNamespace(),
        parent=host,
    )
    side.paint_theme(renderer, scale=150)
    assert "SidebarPane > QWidget" not in side.styleSheet()
    toggle_qss = side.toggle.styleSheet()
    assert renderer.theme(SidebarToggleToneColour) in toggle_qss
    assert renderer.theme(BlockCursorBackgroundColour) in toggle_qss
    assert renderer.theme(BlockCursorForegroundColour) in toggle_qss

    # QtSidebarSearch inherits SidebarSearchField tokens and scales padding with UI zoom.
    search = QtSidebarSearch(SidebarFilter(), host)
    search.paint_theme(renderer, scale=100)
    qss_100 = search.styleSheet()
    assert renderer.theme(SidebarSearchField.search_background_colour) in qss_100
    assert renderer.theme(SidebarSearchField.search_border_colour) in qss_100
    assert renderer.theme(PrimaryColour) in qss_100
    assert search.palette().color(QPalette.ColorRole.PlaceholderText).name().lower() == (
        renderer.theme(SidebarSearchField.search_placeholder_colour).lower()
    )
    search.paint_theme(renderer, scale=150)
    assert search.styleSheet() != qss_100


def test_qt_vim_ctrl_v_pastes_clipboard_image_in_normal_and_insert_modes() -> None:
    _app()
    assert any(action is PasteClipboardAction for action, _method in Composer.action_methods)

    pasted_pngs: list[bytes] = []
    composer = QtMessageComposer.__new__(QtMessageComposer)
    composer.editor = SimpleNamespace(isReadOnly=lambda: False, insertPlainText=lambda _t: None)
    composer.show_failure = lambda msg: (_ for _ in ()).throw(AssertionError(msg))
    composer.file_picked = lambda name, data, mime: pasted_pngs.append(data)

    img = QImage(4, 4, QImage.Format.Format_ARGB32)
    img.fill(QColor("#90a827"))
    mime = QMimeData()
    mime.setImageData(img)
    assert composer.paste_mime_data(mime) is True
    assert len(pasted_pngs) == 1
    assert pasted_pngs[0].startswith(b"\x89PNG\r\n\x1a\n")

    # Clipboard text fallback dispatches through `editing_mode.insert_text`.
    inserted: list[str] = []
    composer.editor = SimpleNamespace(
        isReadOnly=lambda: False,
        editing_mode=SimpleNamespace(insert_text=lambda _ed, text: inserted.append(text)),
    )
    text_mime = QMimeData()
    text_mime.setText("pasted text")
    assert composer.paste_mime_data(text_mime) is True
    assert inserted == ["pasted text"]


def test_qt_ui_zoom_scales_tab_chrome_and_scrollbars() -> None:
    _app()
    scheme = SCHEMES[0]
    renderer = QtLineRenderer(scheme, LinkContext(None, ()), DiffSettings())
    clock = SimpleNamespace(enabled=False, scrolling=False)
    tabs = QtSessionTabBar(clock, QColor("#90a827"), QColor("#c3c3c3"), QColor("#888888"))
    tabs.show_tabs([("#comms", "c1")])
    gap_100 = tabs.scaled_tab_gap()
    slot_100 = tabs._close_slot_metrics()
    tabs.apply_scale(150)
    assert tabs.scaled_tab_gap() > gap_100
    assert tabs._close_slot_metrics()[0] > slot_100[0]
    assert "width: 18px;" in _scrollbar_qss(renderer, scale=150)
    assert "width: 12px;" in _scrollbar_qss(renderer, scale=100)


def test_qt_composer_placeholder_qss_vim_cursor_shape_and_toggle_hover_fg() -> None:
    _app()
    scheme = SCHEMES[0]
    renderer = QtLineRenderer(scheme, LinkContext(None, ()), DiffSettings())

    # 1. Placeholder colour role lives on PromptComposer (shared base) and renders via QSS.
    assert PromptComposer.placeholder_colour is InputPlaceholderToneColour
    expected_placeholder = renderer.theme(PromptComposer.placeholder_colour).lower()

    fake_composer = SimpleNamespace(
        settings=SimpleNamespace(ui=SimpleNamespace(key_mode=VimNormal)),
    )
    editor = ComposerEditor(fake_composer)
    # Vim Normal: block cursor + overwriteMode True.
    assert editor.overwriteMode() is True
    assert editor.cursorWidth() >= max(6, editor.fontMetrics().averageCharWidth())
    # Standard mode switches immediately to a thin beam cursor + overwriteMode False.
    fake_composer.settings.ui.key_mode = Standard
    editor.follow_key_mode()
    assert editor.overwriteMode() is False
    assert editor.cursorWidth() < editor.fontMetrics().averageCharWidth()
    # Switching back to Vim Normal restores the block cursor.
    fake_composer.settings.ui.key_mode = VimNormal
    editor.follow_key_mode()
    assert editor.overwriteMode() is True
    assert editor.cursorWidth() >= max(6, editor.fontMetrics().averageCharWidth())

    # 2. QtSidebarSearch includes placeholder-text-color in QSS (not palette-only).
    search = QtSidebarSearch(SidebarFilter())
    search.paint_theme(renderer)
    assert f"placeholder-text-color: {expected_placeholder}" in search.styleSheet().lower()

    # 3. QtSideBarToggle stores inherited hover foreground colour for vertical paintEvent.
    host = QWidget()
    layout = SidebarLayout(
        SimpleNamespace(current_terminals=lambda: (), store_terminals=lambda _t: None),
        TerminalOrigin(),
    )
    side = QtSideBar(
        layout,
        ChannelsSidebarPlacement,
        QWidget(host),
        heading=lambda: "All",
        laid_out=lambda: None,
        client=SimpleNamespace(),
        parent=host,
    )
    side.toggle.paint_theme(renderer)
    assert side.toggle._hover_fg_colour is not None
    assert side.toggle._hover_fg_colour.name().lower() == renderer.theme(SidebarToggleFace.hover_foreground_colour).lower()
    assert side.toggle._fg_colour is not None
    assert side.toggle._fg_colour.name().lower() == renderer.theme(SidebarToggleFace.foreground_colour).lower()

    # 4. QtTabMarquee.animation_visible handles deleted QtSessionTabBar cleanly.
    clock = SimpleNamespace(enabled=False, scrolling=False)
    tabs = QtSessionTabBar(clock, QColor("#90a827"), QColor("#c3c3c3"), QColor("#888888"))
    marquee = tabs.marquee
    shiboken6.delete(tabs)
    assert marquee.animation_visible is False


def test_qt_composer_embeds_real_neovim_normal_insert_visual_command_and_escape_boundary() -> None:
    """Real embedded Neovim (`nvim`) drives Qt `ComposerEditor`: text objects (`diw`),
    Visual selection highlights (`vbb`), Command mode (`:`), block/beam cursor, and
    `<Esc>` engine boundary leaving idle Normal to focus conversation history."""
    from pyqt_reactive.theming import ColorScheme
    from qasync import QEventLoop

    app = _app()

    class _NeovimHost(HostsNeovim):
        def __init__(self) -> None:
            self.theme = SimpleNamespace(color_scheme=ColorScheme())
            self.notices: list[tuple[str, str, str]] = []

        def start_neovim_task(self, coro):
            return asyncio.get_running_loop().create_task(coro)

        def notify(self, message: str, *, title: str = "", severity: str = "information") -> None:
            self.notices.append((title, severity, message))

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    async def _exercise() -> None:
        nv_host = _NeovimHost()
        focused_messages: list[bool] = []
        refreshed_labels: list[str] = []
        fake_composer = SimpleNamespace(
            settings=SimpleNamespace(ui=SimpleNamespace(key_mode=VimNormal)),
            offers=SimpleNamespace(isVisible=lambda: False, show_offers=lambda _t, _o: None),
            host=SimpleNamespace(
                app=nv_host,
                messages=SimpleNamespace(setFocus=lambda: focused_messages.append(True)),
            ),
            refresh_editing_mode=lambda: refreshed_labels.append(editor.editing_mode.label),
        )
        editor = ComposerEditor(fake_composer)
        try:
            async def _wait_for(predicate, *, timeout: float = 5.0) -> None:
                deadline = asyncio.get_running_loop().time() + timeout
                while not predicate():
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError(
                            f"timed out waiting: text={editor.toPlainText()!r} "
                            f"label={editor.editing_mode.label!r} "
                            f"regions={len(editor.extraSelections())} "
                            f"focused_messages={focused_messages}"
                        )
                    await asyncio.sleep(0.02)

            def _press(key: Qt.Key, text: str = "", mods: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
                ev = QKeyEvent(QEvent.Type.KeyPress, key, mods, text)
                editor.keyPressEvent(ev)

            # Real Neovim starts in NORMAL with block cursor.
            await _wait_for(lambda: editor.editing_mode.label == "NORMAL" and editor.editing_mode.completed)
            assert editor.overwriteMode() is True

            # Enter INSERT, type "hello world", check beam cursor.
            _press(Qt.Key.Key_I, "i")
            for ch in "hello world":
                key = Qt.Key.Key_Space if ch == " " else getattr(Qt.Key, f"Key_{ch.upper()}")
                _press(key, ch)
            await _wait_for(lambda: editor.toPlainText() == "hello world" and editor.editing_mode.label == "INSERT")
            assert editor.overwriteMode() is False

            # Real Vim text object: <Esc> -> NORMAL, `b` -> "world", `diw` -> deletes "world"!
            _press(Qt.Key.Key_Escape)
            await _wait_for(lambda: editor.editing_mode.label == "NORMAL")
            assert editor.overwriteMode() is True
            for ch in "bdiw":
                _press(getattr(Qt.Key, f"Key_{ch.upper()}"), ch)
            await _wait_for(lambda: editor.toPlainText() == "hello ")

            # Real Visual selection: `vhhh` paints Qt ExtraSelections!
            for ch in "vhhh":
                _press(getattr(Qt.Key, f"Key_{ch.upper()}"), ch)
            await _wait_for(
                lambda: editor.editing_mode.label == "VISUAL" and len(editor.extraSelections()) > 0
            )

            # <Esc> exits Visual -> Normal and clears ExtraSelections.
            _press(Qt.Key.Key_Escape)
            await _wait_for(
                lambda: editor.editing_mode.label == "NORMAL" and len(editor.extraSelections()) == 0
            )

            # `:` enters real Neovim COMMAND mode (live command line shown in badge), `<Esc>` exits back to NORMAL.
            _press(Qt.Key.Key_Colon, ":")
            await _wait_for(lambda: editor.editing_mode.label == "COMMAND :")
            _press(Qt.Key.Key_Escape)
            await _wait_for(lambda: editor.editing_mode.label == "NORMAL")

            # `<Esc>` in idle NORMAL crosses `StandardEditingAction` engine boundary -> focuses messages, keeping draft!
            assert focused_messages == []
            _press(Qt.Key.Key_Escape)
            await _wait_for(lambda: focused_messages == [True])
            assert editor.toPlainText() == "hello "
            assert nv_host.notices == []
        finally:
            await editor.editing_mode.close()
            await nv_host.close_neovim()

    try:
        loop.run_until_complete(_exercise())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_touch_modality_suppresses_sticky_hover_and_standard_attaches_cleanly(monkeypatch) -> None:
    """Android (`TouchInput`) drops `:hover` QSS and `WA_Hover` so taps never stick highlighted;
    `Standard().attach_surface(ComposerEditor)` succeeds without Textual's `editor.history`."""
    from toad.client import platform as toad_platform
    from toad.client.platform import AndroidPlatform, LinuxPlatform
    from toad.qt.menu import QtMenu, platform_input

    _app()
    scheme = SCHEMES[0]
    renderer = QtLineRenderer(scheme, LinkContext(None, ()), DiffSettings())

    assert LinuxPlatform.input_modality is KeyboardInput
    assert AndroidPlatform.input_modality is TouchInput
    assert KeyboardInput.hover_highlights is True
    assert TouchInput.hover_highlights is False
    assert TouchInput.hover_rule("QLabel:hover { color: red; }") == ""
    assert ":hover" not in TouchInput.hover_or_pressed("QPushButton", "background: red;")
    assert ":pressed" in TouchInput.hover_or_pressed("QPushButton", "background: red;")

    # Under AndroidPlatform, QtSideBarToggle, _scrollbar_qss, and QtMenu omit `:hover` rules.
    monkeypatch.setattr(toad_platform, "host", AndroidPlatform)
    assert platform_input() is TouchInput
    assert ":hover" not in _scrollbar_qss(renderer)

    host = QWidget()
    layout = SidebarLayout(
        SimpleNamespace(current_terminals=lambda: (), store_terminals=lambda _t: None),
        TerminalOrigin(),
    )
    side = QtSideBar(
        layout,
        ChannelsSidebarPlacement,
        QWidget(host),
        heading=lambda: "All",
        laid_out=lambda: None,
        client=SimpleNamespace(),
        parent=host,
    )
    side.toggle.paint_theme(renderer)
    assert ":hover" not in side.toggle.styleSheet()
    assert side.toggle.testAttribute(Qt.WidgetAttribute.WA_Hover) is False

    menu = QtMenu(host)
    menu.paint(renderer)
    assert ":hover" not in menu.styleSheet()
    assert ":pressed" in menu.styleSheet()

    # Standard key mode attaches cleanly inside a running asyncio loop (regression for #2374).
    async def _attach_standard() -> None:
        fake_composer = SimpleNamespace(
            settings=SimpleNamespace(ui=SimpleNamespace(key_mode=Standard)),
        )
        editor = ComposerEditor(fake_composer)
        assert editor._attached_mode is editor._editing_mode
        assert editor.overwriteMode() is False

    asyncio.run(_attach_standard())
