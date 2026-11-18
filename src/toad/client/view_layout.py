"""How a view follows its layout and visibility settings, owned once for both frontends.

A setting's `Effect` reaches the open widgets of a capability through the settings scope
that changed (the app for an app-wide setting, the view for its own override). These are
the capabilities: Textual's widgets and Qt's inherit them, so one changed setting repaints
the same things on both, read through the scope's own (inherited) settings.
"""

from __future__ import annotations

from abc import abstractmethod

from metaclass_registry import AbstractHooksMeta


class LayoutFollower(metaclass=AbstractHooksMeta):
    """A widget that places itself from the layout settings whenever one changes."""

    @abstractmethod
    def apply_layout_preferences(self) -> None:
        """Read the current layout settings and place this widget by them."""


class ConversationColumn:
    """A conversation laid out in the settings' column: at most `column_width` cells wide
    when the column is on, set where `column_alignment` puts it, its scrollbar
    `scrollbar.size` cells. Textual's `ColumnLayout` and Qt's conversation views read this."""

    @staticmethod
    def column_cells(ui) -> int | None:
        """The column's width in cells, or None for the full width."""
        return max(10, ui.column_width) if ui.column else None

    @staticmethod
    def column_offset(alignment, free: int) -> int:
        """How much of the free width lies before the column."""
        return round(free * alignment.share)

    @staticmethod
    def scrollbar_cells(ui) -> int:
        return ui.scrollbar.size
