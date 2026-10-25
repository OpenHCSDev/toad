"""The commander page: a pure view of the frames the commander heartbeat wrote.

Core's CommanderHud derives every field, UnitState included, and the heartbeat
replaces each commander's CommanderFrame every beat. This page keeps no fleet state
and decides nothing: each Core row class picks its widget through MroDispatch.
"""

from __future__ import annotations

import time
from typing import ClassVar

from agent_comms.commander.vibe_check import OverloadDegradation
from agent_comms.commander_hud import CommanderHud, CommanderUnit, HudRow
from metaclass_registry.mro_dispatch import MroDispatch, handles
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, Static

from toad.app_node import ToadNode
from toad.core.events import CommanderHudChanged
from toad.core_event_carrier import CoreEventReceiver
from toad.screens.modal import ModalScreen


class HudRowWidgets(MroDispatch):
    """One widget per Core row class; a new row class declares its widget here."""

    def widget(self, row: OverloadDegradation | HudRow) -> Widget:
        return type(self).handler_for(type(row))(self, row)

    def frames(self, huds: tuple[CommanderHud, ...]) -> tuple[Widget, ...]:
        """Every commander's frame; with none written yet, the line saying so."""
        return tuple(widget for hud in huds for widget in self.frame(hud)) or (
            Static("Waiting for the commander heartbeat.", markup=False),
        )

    def frame(self, hud: CommanderHud) -> tuple[Widget, ...]:
        """The load line, then Core's rows in the order CommanderHud.rows declares."""
        return (
            Static(
                f"Commander {hud.commander.name}", markup=False, classes="hud-commander"
            ),
            self.widget(hud.load),
            *(self.widget(row) for row in hud.rows()),
        )

    @handles(OverloadDegradation)
    def load(self, load: OverloadDegradation) -> Widget:
        return Static(str(load), markup=False, classes="hud-load")

    @handles(HudRow)
    def row(self, row: HudRow) -> Widget:
        """Phases, the fork roll call and each plan's finished count are one line each."""
        return Static(row.line(), markup=False, classes="hud-row")

    @handles(CommanderUnit)
    def unit(self, card: CommanderUnit) -> Widget:
        lines = [
            f"{card.state.__name__}  {card.unit.name}  -> {card.state.action}",
            f"  {card.clock.line(time.time())}; strikes {card.strikes}",
        ]
        for order in card.orders:
            lines.append(
                f"  {order.problem} ({order.order}) {order.state}: {order.text}"
            )
            lines.append(
                f"    {order.progress.line}; timers up {len(order.review_timers_up)}; "
                f"strikes {order.strikes}; unjudged edits {order.unjudged_edits}"
            )
        lines.extend(f"  ready #{pr.number} at {pr.head[:9]}" for pr in card.ready_prs)
        lines.extend(f"  draft #{pr.number} at {pr.head[:9]}" for pr in card.draft_prs)
        return Static("\n".join(lines), markup=False, classes="hud-unit")


class CommanderPage(CoreEventReceiver, ToadNode, ModalScreen[None]):
    """Every unit's state, orders and PRs, in the UnitState family's declared order."""

    BINDINGS: ClassVar = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    CommanderPage { align: center middle; background: $background 40%; }
    CommanderPage > Vertical {
        width: 95%; height: 95%; padding: 1;
        border: solid $primary; background: $surface;
    }
    CommanderPage #hud-rows { height: 1fr; scrollbar-gutter: stable; }
    CommanderPage .hud-unit { margin-bottom: 1; }
    CommanderPage .hud-commander { text-style: bold reverse; }
    CommanderPage .hud-load { text-style: bold; margin-bottom: 1; }
    CommanderPage Button { dock: bottom; margin-top: 1; }
    """

    widgets = HudRowWidgets()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield VerticalScroll(*self.widgets.frames(()), id="hud-rows")
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
        rows = self.query_one("#hud-rows", VerticalScroll)
        await rows.remove_children()
        await rows.mount_all(self.widgets.frames(event.huds))

    def observation_failed(self, error: Exception) -> None:
        rows = self.query_one("#hud-rows", VerticalScroll)
        rows.remove_children()
        rows.mount(Static(f"Commander rows unavailable: {error}", markup=False))

    @on(Button.Pressed, "#commander-close")
    def action_close(self) -> None:
        self.dismiss(None)
