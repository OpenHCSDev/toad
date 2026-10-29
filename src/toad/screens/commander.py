"""Native views of Core's declaration-owned commander groups and tables."""

from __future__ import annotations

import time
from dataclasses import replace

from agent_comms.commander_hud import CommanderHud, CommanderUnit, HudRecord, HudSection
from agent_comms.coordination_errors import DeferredRead
from agent_comms.disclosure_text import (
    AccentTone, ErrorTone, HudTone, SuccessTone, ViewTable, WarningTone,
)
from agent_comms.errors import RelationViolationError, RouteChangedError, ToolRefusedError
from agent_comms.task_attachments.commander_pings import AlarmGroup, AlarmSection
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.ui_model.observation import ReadCommanderUnit, UnreadableHistory
from agent_comms.ui_model.unit_state import HudGroup
from agent_comms.work_branches import WorkBranchError
from metaclass_registry.mro_dispatch import MroDispatch, handles
from textual import on, work
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, Vertical, VerticalGroup, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.style import Style
from textual.widgets import Button, Checkbox, Collapsible, Input, Static
from ui_theme.scheme import (
    AccentColour, ErrorColour, ForegroundMutedColour, SuccessColour, ThemeColour, WarningColour,
)

from toad.app_node import ToadNode
from toad.core.events import CommanderHudChanged, CommanderHudFailed
from toad.core_event_carrier import CoreEventReceiver
from toad.screens.modal import DismissibleScreen
from toad.widget_actions import DismissAction
from toad.widgets.declared_disclosure import (
    DeclaredDisclosure, DisclosureEntry, DisclosureKey, DisclosedValue, RootKey,
)
from toad.widgets.declared_table import DeclaredTable
from toad.widgets.sidebar_tree import KeyedRows


class UnitTone(MroDispatch):
    """Bind Core's shared tone tiers to native theme colours, not group semantics."""

    @classmethod
    def of(cls, tone: type[HudTone]) -> type[ThemeColour]:
        return cls.handler_for(tone)(tone)

    @handles(HudTone)
    @staticmethod
    def ordinary(tone: type[HudTone]) -> type[ThemeColour]:
        return ForegroundMutedColour

    @handles(WarningTone)
    @staticmethod
    def attention(tone: type[WarningTone]) -> type[ThemeColour]:
        return WarningColour

    @handles(AccentTone)
    @staticmethod
    def accent(tone: type[AccentTone]) -> type[ThemeColour]:
        return AccentColour

    @handles(SuccessTone)
    @staticmethod
    def success(tone: type[SuccessTone]) -> type[ThemeColour]:
        return SuccessColour

    @handles(ErrorTone)
    @staticmethod
    def error(tone: type[ErrorTone]) -> type[ThemeColour]:
        return ErrorColour


class CommanderTable(DeclaredTable[HudRecord]):
    class Selected(Message):
        def __init__(self, record: HudRecord | None) -> None:
            self.record = record
            super().__init__()

    def row_tone(self, record: HudRecord) -> type[ThemeColour]:
        return UnitTone.of(record.hud_group.tone)

    def preferred_entity(self) -> DisclosureKey:
        return self.query_ancestor(CommanderFrameView).selection_key

    def selection_changed(self) -> None:
        frame = self.query_ancestor(CommanderFrameView)
        record = self.selected
        key = DisclosedValue.of(record).sequence_key()
        if self.has_focus or key == frame.selection_key:
            self.post_message(self.Selected(record))


class CommanderGroup(KeyedRows[type[HudRecord]], VerticalGroup):
    """One native band really contains its rows, including ready unheld plan phases."""

    def __init__(self, section: HudSection) -> None:
        self.section = section
        self.heading = Static("", markup=False, classes="hud-group-heading")
        self.table_body = VerticalGroup()
        super().__init__()
        self.call_after_refresh(self.render_section)

    def compose(self) -> ComposeResult:
        yield self.heading
        yield self.table_body

    @property
    def member_container(self) -> VerticalGroup:
        return self.table_body

    @property
    def rows(self) -> dict[type[HudRecord], CommanderTable]:
        return {table.source.record: table for table in self.table_body.query_children(CommanderTable)}

    @property
    def sources(self) -> dict[type[HudRecord], ViewTable[HudRecord]]:
        return {table.record: table for table in self.section.tables}

    def create_row(self, key: type[HudRecord]) -> CommanderTable:
        return CommanderTable(self.sources[key])

    def update_row(self, key: type[HudRecord], row: CommanderTable) -> None:
        row.present(self.sources[key])

    def present(self, section: HudSection) -> None:
        self.section = section
        self.call_after_refresh(self.render_section)

    def render_section(self) -> None:
        colour = self.app.colours.colour(UnitTone.of(self.section.group.tone))
        self.heading.update(Content(self.section.heading()).stylize(Style(foreground=colour)))
        self.display = bool(self.section.records)
        keys = tuple(self.sources)
        self.reconcile_keys(keys, changed=frozenset(keys))


class CommanderAlarm(Collapsible):
    """Core's compact section stays visible; expansion reveals every original record."""

    DEFAULT_CSS = """
    CommanderAlarm > CollapsibleTitle { width: 1fr; }
    """

    def __init__(self, group: type[AlarmGroup]) -> None:
        self.group = group
        self.original = Static("", markup=False)
        super().__init__(self.original, title=group.heading(), collapsed=True)
        self.display = False

    def present(self, section: AlarmSection, now: float) -> None:
        colour = self.app.colours.colour(UnitTone.of(section.group.tone))
        self.title = Content("\n".join(CommanderHud.alarm_text((section,), now))).stylize(
            Style(foreground=colour))
        self.original.update("\n".join(CommanderHud.alarm_detail((section,), now)))
        self.display = True


class CommanderDetails(MroDispatch, ToadNode, VerticalGroup):
    """The selected native record owns its one bounded original-details read."""

    def __init__(self, commander: ThreadIncarnation) -> None:
        self.commander = commander
        self.card: HudRecord | None = None
        self.status = Static("Highlight a record to read its original details.", markup=False)
        self.original = VerticalGroup()
        super().__init__(classes="hud-detail")

    def compose(self) -> ComposeResult:
        yield self.status
        yield Button("Refresh original details", classes="refresh-unit", compact=True)
        yield self.original

    def present(self, card: HudRecord | None) -> None:
        if self.card == card:
            return
        self.card = card
        self.read_detail()

    @on(Button.Pressed, ".refresh-unit")
    def refresh_detail(self, event: Button.Pressed) -> None:
        event.stop()
        self.read_detail()

    @handles(HudRecord)
    async def record_detail(self, card: HudRecord) -> object:
        return card

    @handles(CommanderUnit)
    async def unit_detail(self, card: CommanderUnit) -> object:
        access = self.app.coordination_access
        observed = await access.preparation.run_thread(access.observation.observed)
        return await observed.process.read(ReadCommanderUnit(
            str(observed.service.root), self.commander, card.unit, card.order_ids,
        ))

    @work(exclusive=True, group="commander-detail")
    async def read_detail(self) -> None:
        card = self.card
        self.original.display = False
        if card is None:
            self.status.update("No records match the filter.")
            return
        label = DisclosedValue.of(card).summary()
        self.status.update(f"Reading original records for {label}…")
        try:
            detail = await type(self).handler_for(type(card))(self, card)
        except (DeferredRead, RelationViolationError, RouteChangedError, ToolRefusedError,
                UnreadableHistory, WorkBranchError) as error:
            if self.is_attached and self.card == card:
                self.status.update(f"Original details unavailable: {error}")
            return
        if not self.is_attached or self.card != card:
            return
        entry = DisclosureEntry(RootKey(type(detail)), "Original details", DisclosedValue.of(detail))
        for view in self.original.query_children(DeclaredDisclosure):
            view.present(entry)
            break
        else:
            self.original.mount(DeclaredDisclosure(entry))
        self.original.display = True
        self.status.update("Original records; unit activity is bounded by Core.")

    def on_unmount(self) -> None:
        self.workers.cancel_group(self, "commander-detail")


class CommanderFrameView(KeyedRows[type[HudGroup]], ToadNode, VerticalGroup):
    """Keep native groups, filters, selection and original details across frame replacement."""

    DEFAULT_CSS = """
    CommanderFrameView .hud-filter { height: auto; }
    CommanderFrameView .hud-filter Input { width: 1fr; }
    CommanderFrameView .hud-filter Checkbox { width: auto; }
    CommanderTable { height: auto; max-height: 50vh; }
    CommanderFrameView .hud-detail { height: auto; }
    CommanderFrameView .refresh-unit { width: auto; margin: 0; }
    CommanderGroup { height: auto; }
    CommanderGroup .hud-group-heading { text-style: bold; }
    """

    def __init__(self, hud: CommanderHud) -> None:
        self.hud = hud
        self.selected = next((record for section in hud.groups() for record in section.records), None)
        self.heading = Static("", markup=False, classes="hud-commander")
        self.status = Static("", markup=False, classes="hud-load")
        self.groups = VerticalGroup()
        self.filter = Input(placeholder="Filter commander records")
        self.needs_hand = Checkbox("Needs hand")
        self.details = CommanderDetails(hud.commander)
        self.alarms = {group: CommanderAlarm(group) for group in AlarmGroup.members_with(AlarmGroup)}
        super().__init__()
        self.call_after_refresh(self.render_frame)

    def compose(self) -> ComposeResult:
        yield self.heading
        yield self.status
        with HorizontalGroup(classes="hud-filter"):
            yield self.filter
            yield self.needs_hand
        yield self.groups
        yield from self.alarms.values()
        yield self.details

    @property
    def selection_key(self) -> DisclosureKey:
        return DisclosedValue.of(self.selected).sequence_key()

    @property
    def sections(self) -> dict[type[HudGroup], HudSection]:
        text = self.filter.value.casefold()
        return {section.group: HudSection(section.group, tuple(
            replace(table, records=tuple(record for record, cells in zip(table.records, table.texts)
                                         if (not self.needs_hand.value or record.needs_hand())
                                         and text in "\n".join(cells).casefold()))
            for table in section.tables
        )) for section in self.hud.groups()}

    @property
    def member_container(self) -> VerticalGroup:
        return self.groups

    @property
    def rows(self) -> dict[type[HudGroup], CommanderGroup]:
        return {view.section.group: view for view in self.groups.query_children(CommanderGroup)}

    def create_row(self, key: type[HudGroup]) -> CommanderGroup:
        return CommanderGroup(self.sections[key])

    def update_row(self, key: type[HudGroup], row: CommanderGroup) -> None:
        row.present(self.sections[key])

    @on(Input.Changed)
    @on(Checkbox.Changed)
    def filter_changed(self) -> None:
        self.call_after_refresh(self.render_frame)

    @on(CommanderTable.Selected)
    def highlight_record(self, event: CommanderTable.Selected) -> None:
        event.stop()
        self.selected = event.record
        self.details.present(event.record)

    def present(self, hud: CommanderHud) -> None:
        self.hud = hud
        self.call_after_refresh(self.render_frame)

    def render_frame(self) -> None:
        self.heading.update(f"Commander {self.hud.commander.name}")
        now = time.time()
        self.status.update(self.hud.status_strip(now))
        for view in self.alarms.values():
            view.display = False
        for section in self.hud.alarms:
            self.alarms[section.group].present(section, now)
        sections = self.sections
        records = {DisclosedValue.of(record).sequence_key(): record
                   for section in sections.values() for record in section.records}
        self.selected = records.get(self.selection_key, next(iter(records.values()), None))
        self.details.present(self.selected)
        keys = tuple(sections)
        self.reconcile_keys(keys, changed=frozenset(keys))


class CommanderPage(KeyedRows[ThreadIncarnation], CoreEventReceiver, DismissibleScreen[None]):
    """Current Core frames preserve table selection, focus and the conversation below."""

    DEFAULT_CSS = """
    CommanderPage { align: center middle; background: $background 40%; }
    CommanderPage > Vertical {
        width: 95%; height: 95%; padding: 0 1;
        border: solid $primary; background: $surface;
    }
    CommanderPage #hud-error { display: none; height: auto; color: $error; }
    CommanderPage #hud-rows { height: 1fr; scrollbar-gutter: stable; }
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
        return {row.hud.commander: row for row in self.member_container.query_children(CommanderFrameView)}

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
        self.huds = tuple(hud for hud in event.huds
                          if not self.commander_name or hud.commander.name == self.commander_name)
        keys = tuple(hud.commander for hud in self.huds)
        self.reconcile_keys(keys, changed=frozenset(keys))
        self.query_one("#hud-empty", Static).display = not self.huds

    @handles(CommanderHudFailed)
    def hud_failed(self, event: CommanderHudFailed) -> None:
        notice = self.query_one("#hud-error", Static)
        notice.update(f"Commander rows unavailable: {' '.join(str(event.error).splitlines())}")
        notice.display = True
