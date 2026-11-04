from __future__ import annotations

from rich.style import Style
from textual.app import ComposeResult
from textual.content import Content
from textual.css.native import NativeDeclaration, Variable
from textual.css.styles import Styles
from textual.reactive import reactive
from textual.view import AUTO, FILL
from toad.widgets.side_bar import SidebarPanelWidget
from textual import containers
from textual.widgets import Static
from ui_theme.scheme import PrimaryColour

from toad.block_navigation import ConversationBlock
from toad.native_style import AutoHeight, PrimaryText, RightPadding
from toad.plan import PlanItem, PlanStatus
from toad.widgets.strike_text import StrikeText
from textual.widget import Widget


class NoPlan(Static):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_style = Style(dim=True, italic=True)


class PlanStatusCell(Widget):
    """A cell of one plan entry shows as strongly as that entry's status says."""

    status: type[PlanStatus]

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.opacity = self.status.opacity


class PlanMarker(PrimaryText, PlanStatusCell, Static):
    ALLOW_SELECT = False

    def __init__(self, status: type[PlanStatus]) -> None:
        self.status = status
        super().__init__(Content(status.marker()))


class PlanText(PrimaryText, PlanStatusCell, StrikeText):

    def __init__(self, entry: PlanItem) -> None:
        self.status = entry.status
        super().__init__(Content(entry.content))


class Plan(
    RightPadding,
    AutoHeight,
    ConversationBlock,
    SidebarPanelWidget,
    containers.Grid,
):
    """The agent's plan; the sidebar draws it flush with its panel."""

    native_theme = (NativeDeclaration.of(Styles.color, Variable(PrimaryColour.name)),)

    entries: reactive[list[PlanItem]] = reactive(list, recompose=True)

    def __init__(self, entries: list[PlanItem]):
        self.previous_statuses: dict[str, type[PlanStatus]] = {}
        super().__init__()
        self.set_reactive(Plan.entries, entries)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.grid_size_columns = 2
        self.styles.grid_columns = (AUTO, FILL)
        self.styles.grid_rows = (AUTO,)
        self.styles.border_title_align = "center"

    def watch_entries(self, old_entries: list[PlanItem], new_entries: list[PlanItem]) -> None:
        self.previous_statuses = {entry.content: entry.status for entry in old_entries}

    def compose(self) -> ComposeResult:
        if not self.entries:
            yield NoPlan("No plan yet")
            return
        for entry in self.entries:
            status = entry.status
            yield PlanMarker(status)
            yield (text := PlanText(entry))
            if status.complete:
                previous = self.previous_statuses.get(entry.content)
                text.complete(animated=previous is not None and not previous.complete)


class ConversationPlan(Plan):
    """A plan posted in the conversation stands apart from the messages around it."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (1, 0, 1, 0)
