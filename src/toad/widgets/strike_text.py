from time import monotonic
from typing import ClassVar

from textual.css.native import DeclaresTheme, NativeDeclaration
from textual.widget import Widget

from textual.content import Content
from textual.reactive import reactive

from toad.native_style import AutoHeight, PrimaryText


class Completion(DeclaresTheme):
    """Whether the text reads as done; each member owns that look."""

    native_theme: ClassVar[tuple[NativeDeclaration, ...]] = ()
    text_style: ClassVar[str] = "none"


class Incomplete(Completion):
    pass


class Complete(PrimaryText, Completion):
    text_style = "strike"


class StrikeText(AutoHeight, Widget):
    strike_time: reactive[float | None] = reactive(None)
    completion: type[Completion] = Incomplete

    def __init__(
        self,
        content: Content,
    ):
        self.content = content
        super().__init__()


    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        return (*super().native_declarations(), *self.completion.declared_theme())

    def complete(self, *, animated: bool = False) -> None:
        """Own native completion paint and schedule animation after layout."""
        if animated:
            self.call_after_refresh(self.strike)
        else:
            self.completion = Complete
            self.styles.text_style = self.completion.text_style
            self.update_node_styles()

    def strike(self) -> None:
        self.strike_time = monotonic()
        self.auto_refresh = 1 / 30

    def render(self) -> Content:
        content = self.content
        if self.strike_time is not None:
            position = int((monotonic() - self.strike_time) * 70)
            content = content.stylize("strike $text-primary", 0, position)
            if position > len(content):
                self.auto_refresh = None
        return content
