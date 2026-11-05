"""Widgets that place themselves from the layout settings, as one family the settings effect applies."""

from __future__ import annotations

from abc import abstractmethod


class FollowsLayoutPreferences:
    """A widget that projects the current layout settings onto itself when they change."""

    @abstractmethod
    def apply_layout_preferences(self) -> None:
        """Read the current layout settings and place this widget by them."""
