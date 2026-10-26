"""Expandable views of the commander's published heartbeat frames."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import ClassVar

from agent_comms.commander_hud import (
    BoardRow, CommanderHud, CommanderUnit, HudRow, QuietUnits,
)
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.ui_model.observation import ReadCommanderUnit
from metaclass_registry.mro_dispatch import MroDispatch, handles
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalGroup, VerticalScroll
from textual.content import Content
from textual.widgets import Button, Collapsible, Pretty, Static

from toad.app_node import ToadNode
from toad.core.events import CommanderHudChanged, CommanderHudFailed
from toad.core_event_carrier import CoreEventReceiver
from toad.screens.modal import ModalScreen
from toad.widgets.sidebar_tree import KeyedRows


class HudRowText(MroDispatch):
    """Core's ordinary rows; units and board entries have their own disclosures."""

    def lines(self, row: HudRow) -> tuple[str, ...]:
        return type(self).handler_for(type(row))(self, row)

    @handles(HudRow)
    def row(self, row: HudRow) -> tuple[str, ...]:
        return (row.line(),)

    @handles(CommanderUnit, QuietUnits, BoardRow)
    def disclosed(self, row: HudRow) -> tuple[str, ...]:
        return ()


class CommanderUnitCard(ToadNode, Collapsible):
    """Retain the unit's disclosure while Core replaces its current card."""

    DEFAULT_CSS = """
    CommanderUnitCard { height: auto; border: none; padding: 0; margin: 0 0 1 0; }
    CommanderUnitCard > CollapsibleTitle {
        height: 1; padding: 0; text-wrap: nowrap; text-overflow: ellipsis;
    }
    CommanderUnitCard > Contents { padding: 0 1; height: auto; }
    CommanderUnitCard Static { height: auto; }
    CommanderUnitCard Button { dock: none; width: auto; margin: 0; }
    CommanderUnitCard .detail-status { color: $text-muted; }
    CommanderUnitCard.-needs-hand > CollapsibleTitle { color: $warning; }
    """

    def __init__(self, commander: ThreadIncarnation, card: CommanderUnit) -> None:
        self.commander = commander
        self.card = card
        self.summary = Static("", markup=False)
        self.detail_status = Static("Open to read original orders and activity.",
                                    markup=False, classes="detail-status")
        self.original_orders = Static("", markup=False)
        self.activity = Pretty({})
        self.activity_view = Collapsible(self.activity, title="Recent activity", collapsed=True)
        self.activity_view.display = False
        super().__init__(
            self.summary, self.detail_status,
            Button("Refresh original details", classes="refresh-unit"),
            self.original_orders, self.activity_view, title="", collapsed=True,
        )
        self.present(card)

    def present(self, card: CommanderUnit) -> None:
        changed = card != self.card
        self.card = card
        self.title = Content(f"{card.unit.name} · {card.state.question}")
        self.set_class(card.needs_hand(), "-needs-hand")
        lines = [
            card.state.action,
            f"{card.clock.line(time.time())}; strikes {card.strikes}",
        ]
        for order in card.orders:
            lines.extend((
                f"{order.problem} ({order.order}) {order.state}: {order.text}",
                f"  {order.progress.line}; timers up {len(order.review_timers_up)}; "
                f"strikes {order.strikes}; unjudged edits {order.unjudged_edits}",
            ))
        lines.extend(f"ready #{pr.number} at {pr.head[:9]}" for pr in card.ready_prs)
        lines.extend(f"draft #{pr.number} at {pr.head[:9]}" for pr in card.draft_prs)
        self.summary.update("\n".join(lines))
        if changed and self.is_mounted and not self.collapsed:
            self.read_detail()

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self:
            event.stop()
            self.read_detail()

    def on_collapsible_collapsed(self, event: Collapsible.Collapsed) -> None:
        if event.collapsible is self:
            event.stop()
            self.workers.cancel_group(self, "commander-detail")

    @on(Button.Pressed, ".refresh-unit")
    def refresh_detail(self, event: Button.Pressed) -> None:
        event.stop()
        self.read_detail()

    @work(exclusive=True, group="commander-detail")
    async def read_detail(self) -> None:
        card = self.card
        self.detail_status.update("Reading original orders and recent activity…")
        access = self.app.coordination_access
        try:
            observed = await access.preparation.run_thread(access.observation.observed)
            detail = await observed.process.read(ReadCommanderUnit(
                str(observed.service.root), self.commander, card.unit,
                tuple(dict.fromkeys(order.order for order in card.orders)),
            ))
        except (ValueError, OSError, RuntimeError) as error:
            if self.is_attached and self.card == card and not self.collapsed:
                self.detail_status.update(f"Original details unavailable: {error}")
            return
        if not self.is_attached or self.collapsed or self.card != card:
            return
        lines = []
        for order in detail.orders:
            lines.extend((f"Original order {order.card.order} · {order.card.problem}",
                          *order.instructions, order.story.line))
            lines.extend(
                f"commit {commit.sha} · "
                f"{datetime.fromtimestamp(commit.at, timezone.utc).isoformat()}"
                for commit in order.commits
            )
        self.original_orders.update("\n\n".join(lines))
        self.activity.update(detail.activity)
        self.activity_view.display = True
        self.detail_status.update("Original records read; activity uses Core's bounded view.")


class CommanderFrameView(KeyedRows[ThreadIncarnation], VerticalGroup):
    """The existing keyed-row capability owns unit retention and ordering."""

    row_text = HudRowText()

    def __init__(self, hud: CommanderHud) -> None:
        self.hud = hud
        self.heading = Static("", markup=False, classes="hud-commander")
        self.status = Static("", markup=False, classes="hud-load")
        self.units = VerticalGroup()
        self.footer = Static("", markup=False)
        self.board_text = Static("", markup=False)
        self.board = Collapsible(self.board_text, title="", collapsed=True)
        super().__init__()

    @property
    def member_container(self) -> VerticalGroup:
        return self.units

    @property
    def rows(self) -> dict[ThreadIncarnation, CommanderUnitCard]:
        return {row.card.unit: row for row in self.units.query_children(CommanderUnitCard)}

    @property
    def cards(self) -> dict[ThreadIncarnation, CommanderUnit]:
        return {card.unit: card for card in self.hud.units}

    def create_row(self, key: ThreadIncarnation) -> CommanderUnitCard:
        return CommanderUnitCard(self.hud.commander, self.cards[key])

    def update_row(self, key: ThreadIncarnation, row: CommanderUnitCard) -> None:
        row.present(self.cards[key])

    def compose(self) -> ComposeResult:
        yield self.heading
        yield self.status
        yield self.units
        yield self.footer
        yield self.board

    def on_mount(self) -> None:
        self.present(self.hud)

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
            keys = tuple(card.unit for card in hud.units)
            self.reconcile_keys(keys, changed=frozenset(keys))


class CommanderPage(
    KeyedRows[ThreadIncarnation], CoreEventReceiver, ToadNode, ModalScreen[None],
):
    """Current Core frames preserve disclosures, focus and the underlying conversation."""

    BINDINGS: ClassVar = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    CommanderPage { align: center middle; background: $background 40%; }
    CommanderPage > Vertical {
        width: 95%; height: 95%; padding: 1;
        border: solid $primary; background: $surface;
    }
    CommanderPage #hud-error { display: none; height: auto; color: $error; }
    CommanderPage #hud-rows { height: 1fr; scrollbar-gutter: stable; }
    CommanderPage CommanderFrameView { height: auto; margin-bottom: 1; }
    CommanderPage Static { height: auto; }
    CommanderPage .hud-commander { text-style: bold reverse; }
    CommanderPage .hud-load { text-style: bold; margin-bottom: 1; }
    CommanderPage #commander-close { dock: bottom; margin-top: 1; }
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
            yield Button("Close (Esc)", id="commander-close")

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

    @on(Button.Pressed, "#commander-close")
    def action_close(self) -> None:
        self.dismiss(None)
