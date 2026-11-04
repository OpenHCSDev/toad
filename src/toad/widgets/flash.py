from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from textual.content import Content
from textual.css.native import DeclaresTheme, ThemeState, NativeDeclaration, Percent, TextVariable, Variable
from textual.css.styles import Styles
from textual.reactive import var
from textual.widgets import Static
from textual.timer import Timer
from ui_theme.scheme import ErrorColour, PrimaryColour, SuccessColour, ThemeColour, WarningColour

from toad.app_node import ToadNode
from toad.native_style import EllipsisOverflow, FillWidth, NoWrap, OneRow


class FlashKind(DeclaresTheme, DeclaredFamily, affix="Flash"):
    """A flash's semantic kind owns its tint and ink; callers select it by name."""

    colour: ClassVar[type[ThemeColour]]

    def __init_subclass__(cls, **keywords: object) -> None:
        super().__init_subclass__(**keywords)
        cls.native_theme = (
            NativeDeclaration.of(Styles.background, Variable(cls.colour.name), Percent(10)),
            NativeDeclaration.of(Styles.color, TextVariable(cls.colour.name)),
        )


class DefaultFlash(FlashKind):
    colour = PrimaryColour


class SuccessFlash(FlashKind):
    colour = SuccessColour


class WarningFlash(FlashKind):
    colour = WarningColour


class ErrorFlash(FlashKind):
    colour = ErrorColour


class Flash(OneRow, FillWidth, NoWrap, EllipsisOverflow, Static, ToadNode):
    flash_timer: var[Timer | None] = var(None)
    kind = ThemeState(SuccessFlash)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.display = False

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_align = "center"

    def flash(
        self,
        content: str | Content,
        *,
        duration: float | None = None,
        style: str = DefaultFlash.declared_name,
    ) -> None:
        """Flash the content for a brief period.

        Args:
            content: Content to show.
            duration: Duration in seconds to show content.
            style: The declared name of a `FlashKind` member.
        """
        if self.flash_timer is not None:
            self.flash_timer.stop()
        self.display = False

        def hide() -> None:
            """Hide the content without reserving a transcript row."""
            self.display = False

        self.update(content)
        self.kind = FlashKind.member_named(style)
        self.display = True

        if duration is None:
            duration = self.app.settings.ui.flash_duration

        self.flash_timer = self.set_timer(duration or 3, hide)
