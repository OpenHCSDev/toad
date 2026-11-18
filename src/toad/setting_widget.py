"""Setting capabilities a widget composes: visibility, and the prompt's input settings."""
from __future__ import annotations

from toad.setting_declarations import EachOpenWidget
from textual.events import Mount
from textual import on
from toad.settings_scope import SettingsReader
from toad.client.prompt_stack import SettingVisible


class SettingVisibility(SettingVisible, SettingsReader):
    """A Textual row the shared `SettingVisible` setting shows on mount."""

    @on(Mount)
    def on_mount(self):
        self.display = self.setting_visible(self.configuration_state)


class PromptSettingEffects:
    """A prompt follows the input box settings: these are their effects on every open prompt."""

    @EachOpenWidget
    def apply_input_layout(self) -> None:
        """Prompt parts read their room from the input box setting when laid out."""
        for part in self.walk_children():
            part.refresh(layout=True)
        self.refresh(layout=True)

    @EachOpenWidget
    def apply_input_text(self) -> None:
        self.update_prompt()
