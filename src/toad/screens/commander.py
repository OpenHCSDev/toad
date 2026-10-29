"""A declaration-driven table over the commander's published heartbeat frames."""

from __future__ import annotations

import time

from agent_comms.commander_hud import (
    BoardRow, CommanderHud, CommanderUnit, HudRow, QuietUnits,
)
from agent_comms.coordination_errors import DeferredRead
from agent_comms.errors import RelationViolationError, RouteChangedError, ToolRefusedError
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.ui_model.observation import ReadCommanderUnit, UnreadableHistory
from agent_comms.ui_model.unit_state import (
    AwaitingApplicationRun, Blocked, Idle, Moving, NeedsCommanderAttention, UnitState, Unreadable,
)
from agent_comms.work_branches import WorkBranchError
from metaclass_registry.mro_dispatch import MroDispatch, handles
from textual import on, work
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, Vertical, VerticalGroup, VerticalScroll
from textual.content import Content
from textual.widgets import Button, Checkbox, Collapsible, DataTable, Input, Static
from ui_theme.scheme import (
    AccentColour, ErrorColour, ForegroundMutedColour, SuccessColour, ThemeColour, WarningColour,
)

from toad.app_node import ToadNode
from toad.core.events import CommanderHudChanged, CommanderHudFailed
from toad.core_event_carrier import CoreEventReceiver
from toad.screens.modal import DismissibleScreen
from toad.widget_actions import DismissAction
from toad.widgets.declared_disclosure import (
    DeclaredDisclosure, DisclosureEntry, DisclosedValue, RootKey,
)
from toad.widgets.declared_table import DeclaredTable
from toad.widgets.sidebar_tree import KeyedRows


class HudRowText(MroDispatch):
    """Core's ordinary rows; units and board entries have their own views."""

    def lines(self, row: HudRow) -> tuple[str, ...]:
        return type(self).handler_for(type(row))(self, row)

    @handles(HudRow)
    def row(self, row: HudRow) -> tuple[str, ...]:
        return (row.line(),)

    @handles(CommanderUnit, QuietUnits, BoardRow)
    def disclosed(self, row: HudRow) -> tuple[str, ...]:
        return ()


class UnitTone(MroDispatch):
    """Core's nominal state family supplies the row's tone through its MRO."""

    @classmethod
    def of(cls, state: type[UnitState]) -> type[ThemeColour]:
        return cls.handler_for(state)(state)

    @handles(NeedsCommanderAttention)
    @staticmethod
    def attention(state: type[NeedsCommanderAttention]) -> type[ThemeColour]:
        return WarningColour

    @handles(Blocked, Unreadable)
    @staticmethod
    def blocked(state: type[UnitState]) -> type[ThemeColour]:
        return ErrorColour

    @handles(AwaitingApplicationRun)
    @staticmethod
    def application(state: type[AwaitingApplicationRun]) -> type[ThemeColour]:
        return AccentColour

    @handles(Moving)
    @staticmethod
    def moving(state: type[Moving]) -> type[ThemeColour]:
        return SuccessColour

    @handles(Idle, UnitState)
    @staticmethod
    def idle(state: type[UnitState]) -> type[ThemeColour]:
        return ForegroundMutedColour


class CommanderTable(DeclaredTable[CommanderUnit], record=CommanderUnit, view="hud"):
    def row_tone(self, record: CommanderUnit) -> type[ThemeColour]:
        return UnitTone.of(record.state)


class CommanderFrameView(ToadNode, VerticalGroup):
    """One current frame, one native table selection, one lazy original-detail pane."""

    DEFAULT_CSS = """
    CommanderFrameView .hud-filter { height: auto; }
    CommanderFrameView .hud-filter Input { width: 1fr; }
    CommanderFrameView .hud-filter Checkbox { width: auto; }
    CommanderTable { height: auto; max-height: 50vh; }
    CommanderFrameView .hud-detail { height: auto; }
    CommanderFrameView .detail-status { color: $text-muted; }
    CommanderFrameView .refresh-unit { width: auto; margin: 0; }
    """

    row_text = HudRowText()

    def __init__(self, hud: CommanderHud) -> None:
        self.hud = hud
        self.heading = Static("", markup=False, classes="hud-commander")
        self.status = Static("", markup=False, classes="hud-load")
        self.table = CommanderTable()
        self.filter = Input(placeholder="Filter units, state, work or changes")
        self.needs_hand = Checkbox("Needs hand")
        self.detail_status = Static("Highlight a unit to read its original records.",
                                    markup=False, classes="detail-status")
        self.original_details = VerticalGroup()
        self.footer = Static("", markup=False)
        self.board_text = Static("", markup=False)
        self.board = Collapsible(self.board_text, title="", collapsed=True)
        super().__init__()

    def compose(self) -> ComposeResult:
        yield self.heading
        yield self.status
        yield self.board
        with HorizontalGroup(classes="hud-filter"):
            yield self.filter
            yield self.needs_hand
        yield self.table
        with VerticalGroup(classes="hud-detail"):
            yield self.detail_status
            yield Button("Refresh original details", classes="refresh-unit", compact=True)
            yield self.original_details
        yield self.footer

    def on_mount(self) -> None:
        self.present(self.hud)

    @on(Input.Changed)
    @on(Checkbox.Changed)
    def filter_changed(self) -> None:
        self.filter_units()

    def filter_units(self) -> None:
        text = self.filter.value.casefold()
        selected = self.table.selected
        self.table.present(
            card for card in self.hud.units
            if (not self.needs_hand.value or card.needs_hand())
            and text in "\n".join(cell.plain for cell in self.table.cells(card)).casefold()
        )
        if self.table.selected != selected:
            self.read_detail()

    @on(DataTable.RowHighlighted)
    @on(DataTable.RowSelected)
    def highlight_unit(self) -> None:
        self.read_detail()

    @on(Button.Pressed, ".refresh-unit")
    def refresh_detail(self, event: Button.Pressed) -> None:
        event.stop()
        self.read_detail()

    @work(exclusive=True, group="commander-detail")
    async def read_detail(self) -> None:
        card = self.table.selected
        self.original_details.display = False
        if card is None:
            self.detail_status.update("No units match the filter.")
            return
        self.detail_status.update(f"Reading original orders and activity for {card.unit.name}…")
        access = self.app.coordination_access
        try:
            observed = await access.preparation.run_thread(access.observation.observed)
            request = ReadCommanderUnit(
                str(observed.service.root), self.hud.commander, card.unit,
                tuple(dict.fromkeys(order.order for order in card.orders)),
            )
            detail = await observed.process.read(request)
        except (
            DeferredRead, RelationViolationError, RouteChangedError,
            ToolRefusedError, UnreadableHistory, WorkBranchError,
        ) as error:
            if self.is_attached and self.table.selected == card:
                self.detail_status.update(f"Original details unavailable: {error}")
            return
        if not self.is_attached or self.table.selected != card:
            return
        entry = DisclosureEntry(
            RootKey(type(detail)), "Original details", DisclosedValue.of(detail),
        )
        for view in self.original_details.query_children(DeclaredDisclosure):
            view.present(entry)
            break
        else:
            self.original_details.mount(DeclaredDisclosure(entry))
        self.original_details.display = True
        self.detail_status.update(f"Original records for {card.unit.name}; activity is bounded by Core.")

    def present(self, hud: CommanderHud) -> None:
        self.hud = hud
        self.heading.update(f"Commander {hud.commander.name}")
        self.status.update("\n".join((
            str(hud.load), *hud.heartbeat.aged_line("heartbeat", time.time()),
        )))
        self.footer.update("\n".join(
            line for row in hud.rows() for line in self.row_text.lines(row)
        ))
        self.board.title = Content(f"{len(hud.board)} standing requests and alerts")
        self.board_text.update("\n".join(BoardRow(entry).line() for entry in hud.board))
        self.board.display = bool(hud.board)
        if self.is_mounted:
            self.filter_units()


class CommanderPage(
    KeyedRows[ThreadIncarnation], CoreEventReceiver, DismissibleScreen[None],
):
    """Current Core frames preserve table selection, focus and the conversation below."""

    DEFAULT_CSS = """
    CommanderPage { align: center middle; background: $background 40%; }
    CommanderPage > Vertical {
        width: 95%; height: auto; max-height: 95%; padding: 0 1;
        border: solid $primary; background: $surface;
    }
    CommanderPage #hud-error { display: none; height: auto; color: $error; }
    CommanderPage #hud-rows { height: auto; max-height: 100%; scrollbar-gutter: stable; }
    CommanderPage CommanderFrameView { height: auto; }
    CommanderPage Static { height: auto; }
    CommanderPage .hud-commander { text-style: bold reverse; }
    CommanderPage .hud-load { text-style: bold; }
    CommanderPage #commander-close { dock: bottom; margin: 0; }
    """

    def __init__(self, commander: str = "") -> None:
        self.commander_name = commander
        self.huds: tuple[CommanderHud, ...] = ()
        super().__init__()

    @property
    def member_container(self) -> VerticalScroll:
        return self.query_one("#hud-rows", VerticalScroll)

    @property
    def rows(self) -> dict[ThreadIncarnation, CommanderFrameView]:
        return {
            row.hud.commander: row
            for row in self.member_container.query_children(CommanderFrameView)
        }

    @property
    def frames(self) -> dict[ThreadIncarnation, CommanderHud]:
        return {hud.commander: hud for hud in self.huds}

    def create_row(self, key: ThreadIncarnation) -> CommanderFrameView:
        return CommanderFrameView(self.frames[key])

    def update_row(self, key: ThreadIncarnation, row: CommanderFrameView) -> None:
        row.present(self.frames[key])

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("", id="hud-error", markup=False)
            with VerticalScroll(id="hud-rows"):
                yield Static("Waiting for the commander heartbeat.", id="hud-empty", markup=False)
            yield Button("Close", id="commander-close", compact=True,
                         action=f"screen.{DismissAction.binding_name()}")

    def on_mount(self) -> None:
        access = self.app.coordination_access
        self.subscribe_core(access.events)
        access.show_commander(self, True)

    def on_unmount(self) -> None:
        self.app.coordination_access.show_commander(self, False)
        self.close_core_events()

    @handles(CommanderHudChanged)
    async def hud_changed(self, event: CommanderHudChanged) -> None:
        error = self.query_one("#hud-error", Static)
        error.update("")
        error.display = False
        self.huds = tuple(
            hud for hud in event.huds
            if not self.commander_name or hud.commander.name == self.commander_name
        )
        keys = tuple(hud.commander for hud in self.huds)
        self.reconcile_keys(keys, changed=frozenset(keys))
        self.query_one("#hud-empty", Static).display = not self.huds

    @handles(CommanderHudFailed)
    def hud_failed(self, event: CommanderHudFailed) -> None:
        notice = self.query_one("#hud-error", Static)
        notice.update(f"Commander rows unavailable: {' '.join(str(event.error).splitlines())}")
        notice.display = True
