from __future__ import annotations

from textual.app import ComposeResult
from textual.content import Content
from textual.reactive import reactive
from textual import containers
from textual.widgets import Static

from toad.block_navigation import ConversationBlock
from toad.plan import PlanItem, PlanStatus


class NonSelectableStatic(Static):
    ALLOW_SELECT = False


class Plan(ConversationBlock, containers.Grid):
    DEFAULT_CLASSES = "block"
    DEFAULT_CSS = """

    Plan {        
        border-top: ascii $secondary;            
        border-bottom: ascii $secondary;
        background: black 10%;        
        margin: 1 0 1 0 !important;   # Special case because the tall border reduces the apparent width           
        padding: 0 1 0 1;        
        height: auto;                        
        grid-size: 2;
        grid-columns: auto 1fr;
        grid-rows: auto;
        border-title-align: center;

        .-no-plan {
            text-style: dim italic;
        }

        .plan {
            color: $text-secondary;
        }
        .status {
            padding: 0 0 0 0;
            color: $text-secondary;
        }
        .status.status-completed {
            color: $text-success;            
        }
        .status-pending {
            opacity: 0.7;
        }          
    }

    """

    entries: reactive[list[PlanItem]] = reactive(list, recompose=True)
    all_complete: reactive[bool] = reactive(False)

    def __init__(
        self,
        entries: list[PlanItem],
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        self.previous_statuses: dict[Content, type[PlanStatus]] = {}
        super().__init__(name=name, id=id, classes=classes)
        self.set_reactive(Plan.entries, entries)

    def watch_entries(self, old_entries: list[PlanItem], new_entries: list[PlanItem]) -> None:
        self.previous_statuses = {entry.content: entry.status for entry in old_entries}

    def compute_all_complete(self) -> bool:
        return bool(self.entries) and all(entry.status.complete for entry in self.entries)

    def watch_all_complete(self, complete: bool) -> None:
        self.set_class(complete, "-all-complete")

    def compose(self) -> ComposeResult:
        if not self.entries:
            yield Static("No plan yet", classes="-no-plan")
            return
        for entry in self.entries:
            yield from entry.status.compose(self, entry, self.previous_statuses.get(entry.content))
