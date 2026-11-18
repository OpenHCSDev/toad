"""Setting capabilities a widget composes: visibility, and the prompt's input settings."""
from __future__ import annotations

from textual.events import Mount
from textual import on
from toad.settings_scope import SettingsReader
from toad.client.prompt_stack import SettingVisible


class SettingVisibility(SettingVisible, SettingsReader):
    """A Textual row the shared `SettingVisible` setting shows on mount."""

    @on(Mount)
    def on_mount(self):
        self.apply_setting_visibility()

    def show_setting(self, visible: bool) -> None:
        self.display = visible
