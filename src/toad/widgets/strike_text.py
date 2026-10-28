from time import monotonic

from textual.widget import Widget

from textual.content import Content
from textual.reactive import reactive


class StrikeText(Widget):
    DEFAULT_CSS = """
    StrikeText {
        height: auto;
        &.-complete {
            text-style: strike;
            color: $text-primary;
        }
    }
    """

    strike_time: reactive[float | None] = reactive(None)

    def __init__(
        self,
        content: Content,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        self.content = content
        super().__init__(name=name, id=id, classes=classes)

    def complete(self, *, animated: bool = False) -> None:
        """Own native completion paint and schedule animation after layout."""
        if animated:
            self.call_after_refresh(self.strike)
        else:
            self.add_class("-complete")

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
