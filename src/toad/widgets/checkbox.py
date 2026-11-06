"""The application's checkbox label policy, shared by ordinary and form controls."""

from textual import widgets

from toad.native_style import ClipOverflow


class Checkbox(ClipOverflow, widgets.Checkbox):
    """Its look is its bases."""
