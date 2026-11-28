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

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem
from pyqt_reactive.widgets.shared.list_item_delegate import LAYOUT_ROLE
from pyqt_reactive.widgets.shared.styled_text_layout import Segment, StyledTextLayout

from toad.key_modes import VimInsert
from toad.message_rows import IrcMessageStyle, MarkdownMessageStyle
from toad.qt.action_shortcuts import _qt_sequences
from toad.qt.composer import Composer
from toad.qt.composer_vim import ComposerVimMode
from toad.qt.history import HistoryRowDelegate
from toad.qt.name_wave import QtNameWaveDelegate


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_qt_sequences_expand_enter_to_return_and_enter() -> None:
    assert [s.toString() for s in _qt_sequences("enter")] == ["Return", "Enter"]
    assert [s.toString() for s in _qt_sequences("ctrl+enter")] == ["Ctrl+Return", "Ctrl+Enter"]
    assert [s.toString() for s in _qt_sequences("shift+enter")] == ["Shift+Return", "Shift+Enter"]
    assert [s.toString() for s in _qt_sequences("G")] == ["Shift+G"]
    assert [s.toString() for s in _qt_sequences("escape")] == ["Esc"]


def test_qt_composer_dismiss_control_preserves_draft_on_escape() -> None:
    cleared: list[bool] = []
    focused_messages: list[bool] = []
    hidden_offers: list[tuple] = []
    refreshed: list[bool] = []

    vim = ComposerVimMode(VimInsert)
    assert vim.accepts_text is True

    composer = Composer.__new__(Composer)
    composer.offers = SimpleNamespace(
        isVisible=lambda: False,
        show_offers=lambda title, offers: hidden_offers.append((title, offers)),
    )
    composer.editor = SimpleNamespace(
        vim_enabled=True,
        vim=vim,
        clear=lambda: cleared.append(True),
        clearFocus=lambda: None,
    )
    composer.host = SimpleNamespace(
        messages=SimpleNamespace(setFocus=lambda: focused_messages.append(True)),
    )
    composer.refresh_editing_mode = lambda: refreshed.append(True)

    # First Escape in Vim INSERT -> switches to NORMAL, draft untouched.
    composer.dismiss_control()
    assert vim.accepts_text is False
    assert cleared == []
    assert refreshed == [True]
    assert focused_messages == []

    # Second Escape in Vim NORMAL -> focuses conversation messages, draft STILL untouched!
    composer.dismiss_control()
    assert cleared == []
    assert focused_messages == [True]
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

    item = QTreeWidgetItem(tree)
    item.setData(0, LAYOUT_ROLE, StyledTextLayout(name=Segment("comms-a"), detail_line="Working", multiline=True))
    item.setBackground(0, QBrush(odd_color))
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
    shifted_bg = _paint_corner(item)
    assert shifted_bg == even_color


def test_wire_message_style_strips_leading_blank_lines_and_qt_sheet_zeros_top_margin() -> None:
    fake_row = SimpleNamespace()
    for style in (MarkdownMessageStyle(), IrcMessageStyle()):
        blocks = style.body(fake_row, "\n\n   \n    indented first line\n\nsecond")
        assert len(blocks) == 1
        assert blocks[0].text == "    indented first line\n\nsecond"

    assert "margin-top: 0px" in HistoryRowDelegate.PREFORMATTED_SHEET
