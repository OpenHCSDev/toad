"""Commander cards are views of Core's observed model, not another order board."""
from __future__ import annotations

from dataclasses import replace
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.ui_model.commander import CommanderModel, ObserveCommander, UnitCard
from textual import containers, on
from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Collapsible, Static

from toad.screens.modal import ModalScreen


class CommanderUnit(Collapsible):
    DEFAULT_CSS = """
    CommanderUnit { padding: 0; margin: 0; }
    CommanderUnit > CollapsibleTitle { height: 1; text-overflow: ellipsis; }
    CommanderUnit Static { height: auto; }
    """

    def __init__(self, card: UnitCard) -> None:
        super().__init__(Static(card.detail.text, markup=False),
                         title=Content(card.line), collapsed=True)
        self.unit = card.unit
        self.position = 0

    def present(self, card: UnitCard, position: int) -> None:
        self.position = position
        self.title = Content(card.line)
        self.query_one(Static).update(card.detail.text)


class CommanderScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    CommanderScreen { align: center middle; }
    CommanderScreen #commander-page {
        width: 98%; height: 95%; border: round $accent; background: $surface;
    }
    CommanderScreen #commander-status { height: 1; padding: 0 1; }
    CommanderScreen #commander-board { height: 3fr; }
    CommanderScreen #commander-alarms { height: 1fr; border-top: solid $accent; padding: 0 1; }
    CommanderScreen #commander-alarms Static { height: auto; }
    """
    BINDINGS = [("escape", "dismiss", "Close commander")]

    def __init__(self, commander: str) -> None:
        super().__init__()
        self.commander_name = commander
        self.rows: dict[ThreadIncarnation, CommanderUnit] = {}
        self.request: ObserveCommander

    def compose(self) -> ComposeResult:
        with containers.Vertical(id="commander-page"):
            yield Static("Opening commander…", id="commander-status", markup=False)
            yield containers.VerticalScroll(id="commander-board")
            with containers.VerticalScroll(id="commander-alarms"):
                yield Static("Alarms", id="commander-alarm-lines", markup=False)

    async def on_mount(self) -> None:
        access = self.app.coordination_access
        try:
            def identify():
                observed = access.observation.observed()
                return ObserveCommander(str(observed.service.root),
                    observed.service.registry.require(self.commander_name).incarnation)
            self.request = await access.preparation.run_thread(identify)
            access.show_commander(self)
        except (ValueError, OSError, RuntimeError) as error:
            self.commander_failed(error)

    def on_unmount(self) -> None:
        self.app.coordination_access.stop_commander(self)

    def commander_failed(self, error: Exception) -> None:
        self.query_one("#commander-status", Static).update(f"Commander unavailable: {error}")
        for row in self.rows.values():
            row.remove()
        self.rows.clear()

    def commander_observed(self, model: CommanderModel) -> None:
        board = self.query_one("#commander-board", containers.VerticalScroll)
        current = {card.unit for card in model.units}
        for unit in self.rows.keys() - current:
            self.rows.pop(unit).remove()
        for position, card in enumerate(model.units):
            if card.unit not in self.rows:
                row = self.rows[card.unit] = CommanderUnit(card)
                row.position = position
                board.mount(row)
            else:
                self.rows[card.unit].present(card, position)
        board.call_after_refresh(board.sort_children, key=lambda row: row.position)
        self.query_one("#commander-status", Static).update(
            f"Commander {model.commander.name} | {len(model.units)} units | "
            "Overdue first · Enter/click a unit to expand · Esc to return")
        self.query_one("#commander-alarm-lines", Static).update(
            "Alarms\n" + ("\n".join(alarm.line for alarm in model.alarms)
                          or "No stalled orders or recorded failed deliveries."))

    @on(Collapsible.Expanded, "CommanderUnit")
    @on(Collapsible.Collapsed, "CommanderUnit")
    def expansion_changed(self, event: Collapsible.Toggled) -> None:
        self.request = replace(self.request, expanded=frozenset(
            row.unit for row in self.rows.values() if not row.collapsed))
        self.app.coordination_access.show_commander(self)
