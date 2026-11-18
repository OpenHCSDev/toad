"""The settings screen both frontends inherit: one form per declared page over the saved
settings' state, a search across every page, edits flushed before a save, and discard.

Textual's `SettingsScreen` and Qt's `QtSettingsScreen` add only their native layout,
tabs and keys, and save the file once the screen closes (Textual awaits the save in its
worker; Qt writes synchronously, since Qt may close the dialog after its loop has stopped).
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING

from formbridge.forms.declared_fields import FormPage

from toad.form_family import FieldForm

if TYPE_CHECKING:
    from toad.preferences import SavedSettings


class SettingsEditing:
    """Every setting the user may edit, one form per declared page, searched by label."""

    pages: Mapping[FormPage, FieldForm]

    @property
    @abstractmethod
    def edited_settings(self) -> SavedSettings:
        """The settings this screen edits: the app's saved settings."""

    @classmethod
    @abstractmethod
    def form_type(cls) -> type[FieldForm]:
        """The frontend's form class; its `pages` builds this screen's forms."""

    def build_pages(self) -> None:
        self.pages = self.form_type().pages(self.edited_settings.state)

    def start_editing(self) -> None:
        """While open, a save first takes the edits typed here but not yet left."""
        self.edited_settings.open_edits.append(self.finish)

    def stop_editing(self) -> None:
        self.edited_settings.open_edits.remove(self.finish)

    def finish(self) -> None:
        """Send every edit typed on any page but not left yet."""
        for form in self.pages.values():
            form.finish()

    def filter_pages(self, term: str) -> None:
        for form in self.pages.values():
            form.filter(term)

    def discard(self) -> None:
        """Throw away the edits not yet saved; the forms repaint from the restored state."""
        self.edited_settings.discard()
