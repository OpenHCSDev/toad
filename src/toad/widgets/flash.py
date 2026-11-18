from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from textual.content import Content
from textual.css.native import DeclaresTheme, ThemeState, NativeDeclaration, Percent, TextVariable, Variable
from textual.css.styles import Styles
from textual.reactive import var
from textual.widgets import Static
from textual.timer import Timer

from toad.app_node import ToadNode
from toad.client.prompt_stack import FlashNotice, FlashTone
from toad.native_style import EllipsisOverflow, FillWidth, NoWrap, OneRow


class FlashKind(DeclaresTheme, DeclaredFamily, affix="Flash"):
    """A flash's Textual theme: the shared `FlashTone` of the same name owns its colour."""

    tone: ClassVar[type[FlashTone]]

    def __init_subclass__(cls, **keywords: object) -> None:
        super().__init_subclass__(**keywords)
        cls.tone = FlashTone.member_named(cls.declared_name)
        cls.native_theme = (
            NativeDeclaration.of(Styles.background, Variable(cls.tone.colour.name), Percent(10)),
            NativeDeclaration.of(Styles.color, TextVariable(cls.tone.colour.name)),
        )


class DefaultFlash(FlashKind):
    pass


class SuccessFlash(FlashKind):
    pass


class WarningFlash(FlashKind):
    pass


class ErrorFlash(FlashKind):
    pass


class Flash(FlashNotice, OneRow, FillWidth, NoWrap, EllipsisOverflow, Static, ToadNode):
    """The transient notice; `FlashNotice` owns the flash procedure, this paints it."""

    flash_timer: var[Timer | None] = var(None)
    kind = ThemeState(SuccessFlash)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.display = False

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_align = "center"

    @property
    def settings(self):
        return self.app.settings

    def show_flash(self, content: str | Content, tone: type[FlashTone]) -> None:
        self.display = False
        self.update(content)
        self.kind = FlashKind.member_named(tone.declared_name)
        self.display = True

    def hide_flash(self) -> None:
        """Hide the content without reserving a transcript row."""
        self.display = False

    def stop_flash_timer(self) -> None:
        if self.flash_timer is not None:
            self.flash_timer.stop()

    def start_flash_timer(self, seconds: float) -> None:
        self.flash_timer = self.set_timer(seconds, self.hide_flash)
