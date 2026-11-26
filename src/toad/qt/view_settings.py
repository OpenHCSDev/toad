"""A Qt conversation view's reactions to its settings, over the shared capabilities.

`ConversationView` and `QtThreadView` inherit `QtViewSettings`: a changed setting's `Effect`
reaches this view's widgets of a capability (`settings_widgets`), and the view itself is a
`LayoutFollower` laying its conversation out in the settings' column (`ConversationColumn`),
read through the view's own configuration, so a per-view override repaints the view at once.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from toad.client.view_layout import ConversationColumn, LayoutFollower
from toad.qt.overlay_scrollbar import OverlayScrollBar


def capability_widgets(root: QWidget, widget_type: type) -> list:
    """``root`` and its descendants that compose ``widget_type`` (an `Effect`'s capability)."""
    return [widget for widget in (root, *root.findChildren(QWidget)) if isinstance(widget, widget_type)]


class QtViewSettings(LayoutFollower, ConversationColumn):
    """The view's settings scope as an `Effect` sees it, and its column layout."""

    def settings_widgets(self, widget_type):
        return capability_widgets(self, widget_type)

    def apply_layout_preferences(self) -> None:
        """The conversation takes the column's width (all of it with the column off), set
        where the column alignment puts it; the transcript's scrollbar takes the setting's
        cells beside the text, and draws its `overlay` cells over the text while it moves."""
        ui = self.configuration_state.fields.ui
        cell = self.fontMetrics().averageCharWidth()
        width = self.width()
        cells = self.column_cells(ui)
        column = width if cells is None else min(width, cells * cell)
        left = self.column_offset(ui.column_alignment, width - column)
        margins = self.layout().contentsMargins()
        self.layout().setContentsMargins(left, margins.top(), width - column - left, margins.bottom())
        bar = self.messages.verticalScrollBar()
        bar.setFixedWidth(self.scrollbar_cells(ui) * cell)
        OverlayScrollBar.follow(self.messages, self.messages.animation_clock, self.messages.rows.app_renderer,
                                ui.scrollbar.overlay * cell)
        self.messages.apply_font_scale(ui.message_font_scale)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.apply_layout_preferences()
        self.messages.apply_buffer_viewports()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        # A page laid out while another tab shows takes its column when it is shown.
        if self.isVisible():
            self.apply_layout_preferences()
