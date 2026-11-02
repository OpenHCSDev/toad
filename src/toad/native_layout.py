"""Native widgets declare their layout before their first stylesheet application."""

from typing import ClassVar

from textual.app import App
from textual.css.native import NativeDeclaration, NativeStyleResolver
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

    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        """Providers may extend this cooperatively when their declarations overlap."""
        return self.native_theme

    def apply_native_styles(self, resolver: NativeStyleResolver) -> None:
        super().apply_native_styles(resolver)
        self.styles.merge(resolver.native_styles(*self.native_declarations()))
