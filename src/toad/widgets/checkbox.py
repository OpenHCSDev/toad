"""The application's checkbox label policy, shared by ordinary and form controls."""

from textual import widgets

from toad.native_layout import NativeLayout


class Checkbox(NativeLayout, widgets.Checkbox):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_overflow = "clip"
