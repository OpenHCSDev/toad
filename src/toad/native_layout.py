"""Native widgets declare their layout before their first stylesheet application."""

from textual.app import App
from textual.widget import Widget


class NativeLayout(Widget):
    """The shared registration point for a widget's own layout declarations."""

    def _post_register(self, app: App) -> None:
        super()._post_register(app)
        self.apply_native_layout()

    def apply_native_layout(self) -> None:
        """A widget without additional layout keeps its inherited native defaults."""
