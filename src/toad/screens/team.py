"""Native views of Core's declaration-owned team groups and tables."""

from __future__ import annotations

import time
from dataclasses import replace

from agent_comms.team_hud import TeamHud, Teammate, HudRecord, HudSection
from agent_comms.coordination_errors import DeferredRead
from agent_comms.disclosure_text import (
    AccentTone, DisclosureEntry, DisclosureKey, DisclosureText, ErrorTone, HudTone,
    MutedTone, RootKey, SuccessTone, ViewTable, WarningTone,
)
from agent_comms.errors import RelationViolationError, RouteChangedError, ToolRefusedError
from agent_comms.task_attachments.team_pings import AlarmGroup, AlarmSection
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.order_tools import TeammateRead
from agent_comms.ui_model.observation import ReadOperation, UnreadableHistory
from agent_comms.ui_model.teammate_state import HudGroup
from agent_comms.work_branches import WorkBranchError
from metaclass_registry.mro_dispatch import MroDispatch, handles
from textual import on
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.content import Content
from textual.css.native import NativeDeclaration, Variable
from textual.css.styles import Styles
from textual.message import Message
from textual.style import Style
from textual.widgets import Collapsible, Input, Static
from toad.widgets.acting_button import ActingButton, DismissButton
from toad.widgets.checkbox import Checkbox
from ui_theme.scheme import (
    AccentColour, ErrorColour, MutedColour, SuccessColour, ThemeColour, WarningColour,
)

from toad.app_node import ToadNode
from toad.core.events import TeamHudChanged, TeamHudFailed
from toad.core_event_carrier import CoreEventReceiver
from toad.native_style import (
    AutoHeight,
    AutoWidth,
    Bold,
    DockedBottom,
    FillWidth,
    NoMargin,
    SidePadding,
    StableGutter,
    StartsHidden,
)
from toad.screens.modal import CenteredScreen, DismissibleScreen, ModalPanel, ShadedScreen

from toad.widgets.declared_disclosure import DeclaredDisclosure
from toad.widgets.declared_table import (
    DeclaredTable, EmptyTableSelection, SelectedTableRecord, SelectionView, TableSelection,
)
from toad.widgets.sidebar_tree import KeyedRows
from toad.worker_group import WorkerGroup


class TeamDetailRead(WorkerGroup):
    """Reads the selected record's original; a newer selection supersedes one running."""

    exclusive = True


class UnitTone(MroDispatch):
    """Bind Core's shared tone tiers to native theme colours, not group semantics."""

    @classmethod
    def of(cls, tone: type[HudTone]) -> type[ThemeColour]:
        return cls.handler_for(tone)(tone)

    @handles(MutedTone)
    @staticmethod
    def ordinary(tone: type[MutedTone]) -> type[MutedColour]:
        return MutedColour

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


class TeamTable(DeclaredTable[HudRecord], AutoHeight):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.max_height = "50vh"

    class Selected(Message):
        def __init__(self, selection: TableSelection[HudRecord]) -> None:
            self.selection = selection
            super().__init__()

    def row_tone(self, record: HudRecord) -> type[ThemeColour]:
        return UnitTone.of(record.hud_group.tone)

    def preferred_selection(self) -> TableSelection[HudRecord]:
        return self.query_ancestor(TeamFrameView).selected

    def selection_changed(self) -> None:
        frame = self.query_ancestor(TeamFrameView)
        selection = self.selected
        if selection.key == frame.selected.key:
            self.post_message(self.Selected(selection))

    def selection_highlighted(self) -> None:
        self.post_message(self.Selected(self.selected))


class GroupHeading(Bold, Static):
    """A team group's heading, coloured by the group's tone."""


class TeamGroup(KeyedRows[type[HudRecord]], ToadNode, VerticalGroup):
    """One native band really contains its rows, including ready unheld plan phases."""

    def __init__(self, section: HudSection) -> None:
        self.section = section
        self.heading = GroupHeading("", markup=False)
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
    def rows(self) -> dict[type[HudRecord], TeamTable]:
        return {table.source.record: table for table in self.table_body.query_children(TeamTable)}

    @property
    def sources(self) -> dict[type[HudRecord], ViewTable[HudRecord]]:
        return {table.record: table for table in self.section.tables}

    def create_row(self, key: type[HudRecord]) -> TeamTable:
        return TeamTable(self.sources[key])

    def update_row(self, key: type[HudRecord], row: TeamTable) -> None:
        source = self.sources[key]
        if row.source != source:
            row.present(source)

    def present(self, section: HudSection) -> None:
        self.section = section
        self.call_after_refresh(self.render_section)

    def render_section(self) -> None:
        colour = self.app.colours.colour(UnitTone.of(self.section.group.tone))
        self.heading.update(Content(self.section.heading()).stylize(Style(foreground=colour)))
        self.display = bool(self.section.records)
        keys = tuple(self.sources)
        self.reconcile_keys(keys, changed=frozenset(keys))


class TeamAlarm(ToadNode, Collapsible):
    """Core's compact section stays visible; expansion reveals every original record."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        # The alarm owns its one-line title's width.
        self._title.styles.width = "1fr"

    def __init__(self, group: type[AlarmGroup]) -> None:
        self.group = group
        self.original = Static("", markup=False)
        super().__init__(self.original, title=group.heading(), collapsed=True)
        self.display = False

    def present(self, section: AlarmSection, now: float) -> None:
        colour = self.app.colours.colour(UnitTone.of(section.group.tone))
        self.title = Content("\n".join(TeamHud.alarm_text((section,), now))).stylize(
            Style(foreground=colour))
        self.original.update("\n".join(TeamHud.alarm_detail((section,), now)))
        self.display = True


class RefreshDetail(AutoWidth, NoMargin, ActingButton):
    """Reads the selected record's detail again."""

    async def act(self) -> None:
        self.query_ancestor(TeamDetails).refresh_detail()


class TeamDetails(SelectionView[HudRecord], MroDispatch, ToadNode, VerticalGroup):
    """The selected native record owns its one bounded original-details read."""

    def __init__(self, teammate: ThreadIncarnation) -> None:
        self.teammate = teammate
        self.selection: TableSelection[HudRecord] = EmptyTableSelection()
        self.status = Static("", markup=False)
        self.original = VerticalGroup()
        self.original.display = False
        super().__init__()

    def compose(self) -> ComposeResult:
        yield self.status
        yield RefreshDetail("Refresh original details", compact=True)
        yield self.original

    def present(self, selection: TableSelection[HudRecord]) -> None:
        if self.selection == selection:
            return
        self.selection = selection
        selection.present_to(self)

    def on_mount(self) -> None:
        self.selection.present_to(self)

    def clear_selection(self) -> None:
        TeamDetailRead.cancel_all(self)
        self.original.display = False
        self.status.update("No records match the filter.")

    def show_selection(self, key: DisclosureKey, record: HudRecord) -> None:
        self.read_detail(SelectedTableRecord(key, record))

    def refresh_detail(self) -> None:
        self.selection.present_to(self)

    @handles(HudRecord)
    async def record_detail(self, card: HudRecord) -> object:
        return card

    @handles(Teammate)
    async def unit_detail(self, card: Teammate) -> object:
        access = self.app.coordination_access
        observed = await access.preparation.run_thread(access.observation.observed)
        return await observed.process.read(ReadOperation(str(observed.service.root), TeammateRead(
            frame_owner=self.teammate, unit=card.unit, orders=card.order_ids,
        )))

    @TeamDetailRead.work
    async def read_detail(self, selection: SelectedTableRecord[HudRecord]) -> None:
        self.original.display = False
        card = selection.record
        label = DisclosureText.describe(card).summary
        self.status.update(f"Reading original records for {label}…")
        try:
            detail = await type(self).handler_for(type(card))(self, card)
        except (DeferredRead, RelationViolationError, RouteChangedError, ToolRefusedError,
                UnreadableHistory, WorkBranchError) as error:
            if self.is_attached and self.selection == selection:
                self.status.update(f"Original details unavailable: {error}")
            return
        if not self.is_attached or self.selection != selection:
            return
        entry = DisclosureEntry(RootKey(type(detail)), "Original details", DisclosureText.describe(detail))
        for view in self.original.query_children(DeclaredDisclosure):
            view.present(entry)
            break
        else:
            self.original.mount(DeclaredDisclosure(entry))
        self.original.display = True
        self.status.update("Original records; unit activity is bounded by Core.")

    def on_unmount(self) -> None:
        TeamDetailRead.cancel_all(self)


class TeamHeading(Static):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_style = "bold reverse"


class TeamLoad(Bold, Static):
    """The team's status strip."""


class TeamFilter(FillWidth, Input):
    """Its look is its bases."""


class TeamFrameView(KeyedRows[type[HudGroup]], ToadNode, VerticalGroup):
    """Keep native groups, filters, selection and original details across frame replacement."""

    def __init__(self, hud: TeamHud) -> None:
        self.hud = hud
        self.selected: TableSelection[HudRecord] = EmptyTableSelection()
        self.shown: dict[type[HudGroup], HudSection] = {}
        self.heading = TeamHeading("", markup=False)
        self.status = TeamLoad("", markup=False)
        self.groups = VerticalGroup()
        self.filter = TeamFilter(placeholder="Filter team records")
        self.needs_hand = Checkbox("Needs hand")
        self.details = TeamDetails(hud.teammate)
        self.alarms = {group: TeamAlarm(group) for group in AlarmGroup.members_with(AlarmGroup)}
        super().__init__()
        self.call_after_refresh(self.render_frame)

    def compose(self) -> ComposeResult:
        yield self.heading
        yield self.status
        with HorizontalGroup():
            yield self.filter
            yield self.needs_hand
        yield self.groups
        yield from self.alarms.values()
        yield self.details

    def filtered_sections(self) -> dict[type[HudGroup], HudSection]:
        text = self.filter.value.casefold()
        shown: dict[type[HudGroup], HudSection] = {}
        for section in self.hud.groups:
            tables: list[ViewTable[HudRecord]] = []
            for table in section.tables:
                records = tuple(record for record, cells in zip(table.records, table.texts)
                                if (not self.needs_hand.value or record.needs_hand())
                                and text in "\n".join(cells).casefold())
                tables.append(table if records == table.records else replace(table, records=records))
            shown[section.group] = HudSection(section.group, tuple(tables))
        return shown

    @property
    def member_container(self) -> VerticalGroup:
        return self.groups

    @property
    def rows(self) -> dict[type[HudGroup], TeamGroup]:
        return {view.section.group: view for view in self.groups.query_children(TeamGroup)}

    def create_row(self, key: type[HudGroup]) -> TeamGroup:
        return TeamGroup(self.shown[key])

    def update_row(self, key: type[HudGroup], row: TeamGroup) -> None:
        row.present(self.shown[key])

    @on(Input.Changed)
    @on(Checkbox.Changed)
    def filter_changed(self) -> None:
        self.call_after_refresh(self.render_frame)

    @on(TeamTable.Selected)
    def highlight_record(self, event: TeamTable.Selected) -> None:
        event.stop()
        self.selected = event.selection
        self.details.present(self.selected)

    def present(self, hud: TeamHud) -> None:
        self.hud = hud
        self.call_after_refresh(self.render_frame)

    def focus_selection(self) -> None:
        for table in self.query(TeamTable):
            # Focus needs the prepared semantic record, not allocated native row keys.
            if self.selected.key in table.source.entities:
                table.focus(scroll_visible=False)
                break

    def render_frame(self) -> None:
        focused = any(table.has_focus for table in self.query(TeamTable))
        self.heading.update(f"Team {self.hud.teammate.name}")
        now = time.time()
        self.status.update(self.hud.status_strip(now))
        for view in self.alarms.values():
            view.display = False
        for section in self.hud.alarms:
            self.alarms[section.group].present(section, now)
        self.shown = self.filtered_sections()
        records = {key: record for section in self.shown.values() for table in section.tables
                   for key, record in table.entities.items()}
        self.selected = TableSelection[HudRecord].from_records(records, self.selected.key)
        self.details.present(self.selected)
        keys = tuple(self.shown)
        self.reconcile_keys(keys, changed=frozenset(keys))
        if focused:
            self.call_after_refresh(self.focus_selection)


class TeamPanel(SidePadding, ModalPanel):
    """Its look is its bases."""


class HudError(StartsHidden, Static):
    native_theme = (NativeDeclaration.of(Styles.color, Variable(ErrorColour.name)),)



class HudRows(StableGutter, VerticalScroll):
    """Its look is its bases."""


class HudEmpty(Static):
    """Shown until the first team frame arrives."""


class TeamClose(DockedBottom, NoMargin, DismissButton):
    """Its look is its bases."""


class TeamPage(ShadedScreen, CenteredScreen, KeyedRows[ThreadIncarnation], CoreEventReceiver, DismissibleScreen[None]):
    """Current Core frames preserve table selection, focus and the conversation below."""

    def __init__(self, teammate: str = "") -> None:
        self.team_name = teammate
        self.huds: tuple[TeamHud, ...] = ()
        super().__init__()

    @property
    def member_container(self) -> HudRows:
        return self.query_one(HudRows)

    @property
    def rows(self) -> dict[ThreadIncarnation, TeamFrameView]:
        return {row.hud.teammate: row for row in self.member_container.query_children(TeamFrameView)}

    @property
    def frames(self) -> dict[ThreadIncarnation, TeamHud]:
        return {hud.teammate: hud for hud in self.huds}

    def create_row(self, key: ThreadIncarnation) -> TeamFrameView:
        return TeamFrameView(self.frames[key])

    def update_row(self, key: ThreadIncarnation, row: TeamFrameView) -> None:
        row.present(self.frames[key])

    def compose(self) -> ComposeResult:
        with TeamPanel():
            yield HudError("", markup=False)
            with HudRows():
                yield HudEmpty("Waiting for the team heartbeat.", markup=False)
            yield TeamClose("Close", compact=True)

    def on_mount(self) -> None:
        access = self.app.coordination_access
        self.subscribe_core(access.events)
        access.show_team(self, True)

    def on_unmount(self) -> None:
        self.app.coordination_access.show_team(self, False)
        self.close_core_events()

    @handles(TeamHudChanged)
    async def hud_changed(self, event: TeamHudChanged) -> None:
        error = self.query_one(HudError)
        error.update("")
        error.display = False
        self.huds = tuple(hud for hud in event.huds
                          if not self.team_name or hud.teammate.name == self.team_name)
        keys = tuple(hud.teammate for hud in self.huds)
        self.reconcile_keys(keys, changed=frozenset(keys))
        self.query_one(HudEmpty).display = not self.huds

    @handles(TeamHudFailed)
    def hud_failed(self, event: TeamHudFailed) -> None:
        notice = self.query_one(HudError)
        notice.update(f"Team rows unavailable: {' '.join(str(event.error).splitlines())}")
        notice.display = True
