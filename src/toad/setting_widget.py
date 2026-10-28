"""Setting capabilities a widget composes: visibility, and the prompt's input settings."""
from __future__ import annotations

from typing import TYPE_CHECKING

from toad.setting_declarations import Effect

if TYPE_CHECKING:
    from formbridge.forms.declared_fields import DeclaredField
    from toad.app import ToadApp


class SettingVisibility:
    def __init_subclass__(cls, *, setting: str, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.visibility_setting = setting

    def on_mount(self):
        self.display = self.app.saved_settings.state.get_resolved_value(self.visibility_setting)


class PromptSettingEffects:
    """A prompt follows the input box settings: these are their effects on every open prompt."""

    @staticmethod
    @Effect
    def apply_input_layout(app: ToadApp, field: DeclaredField) -> None:
        """Prompt parts read their room from the input box setting when laid out."""
        for prompt in Effect.open_widgets(app, PromptSettingEffects):
            for part in prompt.walk_children():
                part.refresh(layout=True)
            prompt.refresh(layout=True)

    @staticmethod
    @Effect
    def apply_input_text(app: ToadApp, field: DeclaredField) -> None:
        for prompt in Effect.open_widgets(app, PromptSettingEffects):
            prompt.update_prompt()
