"""Widgets that place themselves from the layout settings, as one family the settings effect applies."""

from __future__ import annotations


class FollowsLayoutPreferences:
    """A widget that projects the current layout settings onto itself when they change.

    Members are Textual widgets, whose metaclass is not ABCMeta, so the family
    cannot be an ABC; a member that forgets the method fails loud when the
    settings effect first reaches it.
    """

    def apply_layout_preferences(self) -> None:
        """Read the current layout settings and place this widget by them."""
        raise NotImplementedError(f"{type(self).__name__} follows layout preferences without applying them")
