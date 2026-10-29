"""Textual-facing: retain the real commander page across Core frame replacements."""

import json
from dataclasses import replace

from agent_comms.commander.vibe_check import OverloadDegradation
from agent_comms.commander_hud import (
    CommanderFrame, CommanderHud, CommanderUnit, CodexUsage, HudRecord, UnreadableUsage,
)
from agent_comms.recorded_time import RecordedEventTime
from agent_comms.standing_rules import ServicePassFailing
from agent_comms.task_attachments.commander_pings import AlarmSection, NewAlarms, RulePing
from agent_comms.thread_identity import RecordedThreadIncarnation
from agent_comms.ui_model.observation import ObserveCommanderHud
from agent_comms.ui_model.unit_state import Detached, Moving, PendingClock
from support.workspace import Workspace
from textual.worker import Worker, WorkerState
from textual.widgets import Button, Static

from toad.comms_root import FailedObservation, UnselectedRoute
from toad.core.events import CommanderHudChanged
from toad.screens.commander import (
    CommanderAlarm, CommanderFrameView, CommanderGroup, CommanderPage, CommanderTable,
)
from toad.widgets.declared_disclosure import (
    DeclaredDisclosure, DisclosureEntry, DisclosedValue, RootKey,
)
from toad.widgets.declared_table import EmptyTableSelection, SelectedTableRecord


def selected(record: HudRecord) -> SelectedTableRecord[HudRecord]:
    return SelectedTableRecord(DisclosedValue.of(record).sequence_key(), record)


def row_maps_cohere(table: CommanderTable) -> bool:
    return (set(table.records) == set(table.entity_keys.values()) == {row.key for row in table.ordered_rows}
            and all(table.records[native].key == entity for entity, native in table.entity_keys.items()))


def published_hud() -> CommanderHud:
    unit = CommanderUnit(
        RecordedThreadIncarnation("hud-worker", 2.0), Detached,
        PendingClock(1.0, 1.0), (), 1, (), (),
    )
    return CommanderHud(
        RecordedThreadIncarnation("claude-code", 1.0), (unit,), (),
        OverloadDegradation.from_orders((), 0, 0),
        (RecordedThreadIncarnation("fork-hud", 2.0),),
        CodexUsage(UnreadableUsage(reason="not requested")), open_pings=(),
    )


async def test_commander_page_survives_unreadable_frames_and_recovers(workspace: Workspace) -> None:
    hud = published_hud()
    unit, = hud.units
    CommanderFrame.replace_all(workspace.comms.root, (hud,))
    frame, = CommanderFrame.matching_in(workspace.comms.root)
    written = json.loads(frame.read_text())
    unreadable = json.dumps({**written, "field_from_a_newer_build": []})
    frame.write_text(unreadable)
    async with workspace.app() as ui:
        app, pilot = ui.textual
        page = CommanderPage()
        await app.push_screen(page)
        notice = page.query_one("#hud-error", Static)
        await ui.until(lambda: notice.display, why="the unreadable frame to reach the page")
        assert "field_from_a_newer_build" in str(notice.render())
        rows = page.query_one("#hud-rows")
        assert [str(row.render()) for row in rows.query(Static)] == [
            "Waiting for the commander heartbeat.",
        ]

        CommanderFrame.replace_all(workspace.comms.root, (hud,))
        await ui.until_shows("Commander claude-code")
        assert not notice.display
        last_good = tuple(rows.children)
        view = rows.query_one(CommanderFrameView)
        await ui.until(lambda: bool(view.query(CommanderTable)), why="the grouped native table to mount")
        table = view.query_one(CommanderTable)
        await ui.until(lambda: table.selected == selected(unit), why="the actual unit to acquire a native row")
        table.focus()
        await pilot.press("enter")
        await ui.until_shows(Detached.action)
        # There is no registered unit behind this published fixture. Its real
        # original-detail refusal must remain visible while observation recovers.
        await ui.until_shows("Original details unavailable:")
        assert str(view.heading.render()) == "Commander claude-code"
        strip = str(view.status.render())
        assert "Load: 0" in strip and "Forks: 1" in strip
        assert hud.usage.line() in strip
        assert view.selected == view.details.selection == selected(unit)

        # Observe the native worker lifecycle, not a patched read method or fake reply.
        events: list[Worker.StateChanged] = []
        view.details.listen(Worker.StateChanged, events.append)
        original_source = table.source
        original_keys = tuple(table.entity_keys.values())
        identical = replace(hud, units=(replace(unit, clock=PendingClock(1.0, 2.0)),))
        view.present(identical)
        await ui.step()
        # A genuinely fresh but equal frozen table must not re-prepare native identities.
        group = table.query_ancestor(CommanderGroup)
        equivalent = replace(group.section, tables=tuple(replace(source) for source in group.section.tables))
        assert equivalent.tables[0] == original_source and equivalent.tables[0] is not original_source
        group.present(equivalent)
        group.render_section()
        await ui.step()
        assert table.source is original_source
        assert tuple(table.entity_keys.values()) == original_keys
        assert table.selected == selected(unit) and row_maps_cohere(table)
        assert not [event for event in events if event.state is WorkerState.PENDING]

        frame.write_text(unreadable)
        await ui.until(lambda: notice.display, why="the next unreadable frame to reach the page")
        assert "field_from_a_newer_build" in str(notice.render())
        assert tuple(rows.children) == last_good
        assert table.has_focus

        repaired = replace(
            hud, units=(replace(unit, strikes=2),),
            forks=(RecordedThreadIncarnation("recovered", 3.0),),
        )
        CommanderFrame.replace_all(workspace.comms.root, (repaired,))
        await ui.until(lambda: view.details.selection == selected(repaired.units[0]),
                       why="changed strikes to invalidate the real selected card")
        await ui.until(lambda: len([event for event in events if event.state is WorkerState.PENDING]) == 1,
                       why="one new original-detail worker for the changed card")
        await ui.until_shows("Original details unavailable:")
        assert not notice.display
        assert rows.query_one(CommanderFrameView) is view
        assert view.query_one(CommanderTable) is table and table.has_focus
        assert table.selected == selected(repaired.units[0])
        assert table.source != original_source
        assert tuple(table.entity_keys.values()) == original_keys and row_maps_cohere(table)
        assert len(view.hud.forks) == 1 and view.hud.forks[0].name == "recovered"
        assert "Forks: 1" in str(view.status.render())
        # Explicit refresh is unconditional, even for an otherwise identical card.
        view.details.query_one(Button).press()
        await ui.until(lambda: len([event for event in events if event.state is WorkerState.PENDING]) == 2,
                       why="explicit Refresh to launch another bounded read")
        recovered_rows = tuple(rows.children)
        failed = FailedObservation(
            OSError("observer process exited"), UnselectedRoute(),
            access=app.coordination_access,
        )
        failed.observe_commander(ObserveCommanderHud())
        await ui.until(lambda: notice.display, why="the observer failure notice")
        assert str(notice.render()) == "Commander rows unavailable: observer process exited"
        assert tuple(rows.children) == recovered_rows
        await pilot.press("escape")
        await ui.step()
        assert app.screen is not page


async def test_a_heartbeat_with_no_frames_still_says_it_is_waiting(workspace: Workspace) -> None:
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        page = CommanderPage()
        await app.push_screen(page)
        await ui.step()
        app.coordination_access.events.publish(CommanderHudChanged(()))
        await ui.step()
        rows = page.query_one("#hud-rows").query(Static)
        assert [str(row.render()) for row in rows] == ["Waiting for the commander heartbeat."]


async def test_selection_survives_filter_clear_refill_group_move_and_resize(workspace: Workspace) -> None:
    hud = published_hud()
    first, = hud.units
    second = replace(first, unit=RecordedThreadIncarnation("second-worker", 3.0))
    hud = replace(hud, units=(first, second))
    CommanderFrame.replace_all(workspace.comms.root, (hud,))
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        page = CommanderPage()
        await app.push_screen(page)
        await ui.until(lambda: bool(page.query(CommanderTable)), why="the native table to mount")
        view = page.query_one(CommanderFrameView)
        table = view.query_one(CommanderTable)
        await ui.until(lambda: table.row_count == 2, why="both original records to acquire native rows")
        table.focus()
        table.move_cursor(row=1, animate=False)
        await ui.until(lambda: view.selected == selected(second), why="the highlighted second record")
        semantic = view.selected.key
        before_keys = tuple(table.entity_keys.values())
        assert set(table.records) == set(before_keys) and row_maps_cohere(table)

        await ui.resize(60, 40)
        await ui.until(lambda: not table.show_header, why="the narrow stacked layout")
        assert table.selected.key == semantic
        assert table.selected == selected(second)
        assert row_maps_cohere(table)
        assert tuple(table.entity_keys.values()) != before_keys  # Anonymous keys came back from add_row.
        await ui.resize(160, 40)
        await ui.until(lambda: table.show_header, why="the wide table layout")
        assert table.selected.key == semantic

        view.filter.value = "nothing-matches-this-record"
        await ui.until(lambda: view.selected == EmptyTableSelection(), why="filter-all empty selection")
        await ui.until(lambda: not view.details.original.display, why="old details to hide")
        assert view.details.selection == EmptyTableSelection()
        assert str(view.details.status.render()) == "No records match the filter."
        await ui.until(lambda: all(native.row_count == 0 for native in view.query(CommanderTable)),
                       why="the native rows to clear too")
        assert all(not native.records and not native.entity_keys for native in view.query(CommanderTable))
        view.filter.value = ""
        await ui.until(lambda: view.selected == selected(first), why="clear-and-refill to choose the first visible record")
        await ui.until(lambda: table.row_count == 2, why="the public native rows to refill")
        table.focus()
        table.move_cursor(row=1, animate=False)
        await ui.until(lambda: view.selected == selected(second), why="the second semantic identity to be selected again")
        moved = replace(second, state=Moving)
        CommanderFrame.replace_all(workspace.comms.root, (replace(hud, units=(first, moved)),))
        await ui.until(lambda: view.selected == selected(moved), why="the original selection to move between groups")
        await ui.until(lambda: any(native.selected == selected(moved) for native in view.query(CommanderTable)),
                       why="the target group to resolve the same semantic key")
        assert view.selected.key == semantic
        await ui.until(lambda: any(native.has_focus and native.selected == selected(moved)
                                   for native in view.query(CommanderTable)),
                       why="native focus to follow its selected semantic record")
        assert view.details.selection == selected(moved)
        assert all(row_maps_cohere(native) for native in view.query(CommanderTable))
        CommanderFrame.replace_all(workspace.comms.root, (replace(hud, units=()),))
        await ui.until(lambda: view.selected == EmptyTableSelection(), why="an actually empty frame")
        CommanderFrame.replace_all(workspace.comms.root, (hud,))
        await ui.until(lambda: view.selected == selected(first), why="a later frame to refill the original records")


async def test_core_summaries_and_alarm_ages_reach_native_disclosures(workspace: Workspace) -> None:
    hud = published_hud()
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        for value in (hud.units[0].strikes, CommanderUnit, Detached):
            disclosed = DisclosedValue.of(value)
            disclosure = DeclaredDisclosure(DisclosureEntry(RootKey(type(value)), "Original", disclosed))
            await app.screen.mount(disclosure)
            disclosure.collapsed = False
            await ui.until(lambda: disclosure.body.display, why="the scalar/class/family body to expand")
            assert str(disclosure.body.render()) == disclosed.source.summary()
            assert disclosed.source.summary() in str(disclosure.title)
        assert DisclosedValue.of(Detached).source.summary() == Detached.declared_name
        assert not str(disclosure.body.render()).startswith("<class ")

        ping = replace(RulePing.capture(ServicePassFailing("native-alarm", 1000, "original error")),
                       since=RecordedEventTime(1000))
        section = AlarmSection(NewAlarms, (ping,))
        alarm = CommanderAlarm(NewAlarms)
        await app.screen.mount(alarm)
        alarm.present(section, 1005)
        alarm.collapsed = False
        first_title = str(alarm.title)
        assert "5s" in first_title
        assert str(alarm.original.render()) == ping.render(1005)
        alarm.present(section, 1065)  # Same membership; painting still owns the new age.
        assert "1m5s" in str(alarm.title) and str(alarm.title) != first_title
        assert str(alarm.original.render()) == ping.render(1065)
        assert not alarm.collapsed
