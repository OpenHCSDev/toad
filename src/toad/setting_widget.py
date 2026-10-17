"""Visibility belongs to its widget declaration, including the first mount."""
from textual.widget import Widget
from toad.forms.declared_views import DeclaredField


class SettingVisibility(Widget):
    def __init_subclass__(cls, *, setting: str, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.visibility_setting = setting

    def on_mount(self):
        state = self.app.saved_settings.state
        self.display = DeclaredField(state, state.parameter_structure.path(self.visibility_setting)).value
