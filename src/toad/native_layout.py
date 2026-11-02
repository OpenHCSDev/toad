"""Native widgets declare their layout before their first stylesheet application."""

from typing import ClassVar

from textual.app import App
from textual.css.native import NativeDeclaration
from textual.theme import Theme
from textual.widget import Widget


class NativeLayout(Widget):
    """The shared registration point for a widget's own layout declarations."""

    def _post_register(self, app: App) -> None:
        super()._post_register(app)
        self.apply_native_layout()

    def apply_native_layout(self) -> None:
        """A widget without additional layout keeps its inherited native defaults."""


class NativeTheme(Widget):
    """Native property declarations follow the app's current theme value owner."""

    native_theme: ClassVar[tuple[NativeDeclaration, ...]] = ()

    def _post_register(self, app: App) -> None:
        super()._post_register(app)
        self.apply_native_theme()

    def on_mount(self) -> None:
        self.apply_native_theme()
        self.app.theme_changed_signal.subscribe(self, self._native_theme_changed)

    def _native_theme_changed(self, theme: Theme) -> None:
        self.apply_native_theme()

    def apply_native_theme(self) -> None:
        self.styles.merge(self.app.stylesheet.native_styles(*self.native_theme))
