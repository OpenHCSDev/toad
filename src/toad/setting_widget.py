"""Setting capabilities a widget composes: visibility, and the prompt's input settings."""
from __future__ import annotations

from toad.setting_declarations import EachOpenWidget


class SettingVisibility:
    def __init_subclass__(cls, *, setting: str, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.visibility_setting = setting

    def on_mount(self):
        self.display = self.app.saved_settings.state.get_resolved_value(self.visibility_setting)


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
