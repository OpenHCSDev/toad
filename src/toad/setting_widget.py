"""Visibility belongs to its widget declaration, including the first mount."""
class SettingVisibility:
    def __init_subclass__(cls, *, setting: str, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.visibility_setting = setting

    def on_mount(self):
        self.display = self.app.saved_settings.state.get_resolved_value(self.visibility_setting)
