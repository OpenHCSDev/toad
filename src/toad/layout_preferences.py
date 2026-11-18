"""Widgets that place themselves from the layout settings, as one family the settings effect applies."""

from __future__ import annotations

from abc import abstractmethod

from textual.widget import Widget

from toad.client.view_layout import LayoutFollower


class FollowsLayoutPreferences(LayoutFollower, Widget):
    """A Textual widget that projects the current layout settings onto itself when they
    change (the shared `LayoutFollower` capability the layout effect reaches)."""
