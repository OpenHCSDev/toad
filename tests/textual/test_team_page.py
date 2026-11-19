"""Textual-facing: retain the real team page across Core frame replacements."""

import json
from dataclasses import replace

from PySide6.QtWidgets import QApplication, QWidget
from agent_comms.nominal.text_digest import TextDigest
from agent_comms.registry.thread_identity import RecordedThreadIncarnation
from agent_comms.storage.recorded_time import RecordedEventTime
from agent_comms.task_attachments.disclosure_text import (
    DisclosureEntry,
    DisclosureText,
    FieldKey,
    RecordKey,
    StructuredText,
)
from agent_comms.task_attachments.team_pings import (
    AlarmSection,
    NewAlarms,
    RulePing,
    TeamUpdateNotice,
)
from agent_comms.team import judge
from agent_comms.team.order import TeamVerbActionOffer
from agent_comms.team.standing_rules import ServicePassFailing
from agent_comms.team.team_hud import (
    AllTeamBoards,
    CodexUsage,
    NamedTeamBoards,
    TeamBoardCut,
    TeamBoardPublicationStore,
    TeamHud,
    TeamPlan,
    UnreadableUsage,
)
from agent_comms.team.team_hud_records import HudRecord, Teammate
from agent_comms.team.vibe_check import OverloadDegradation
from agent_comms.ui_model.observation import ObserveTeamHud, StopTeamHud
from agent_comms.ui_model.teammate_state import Detached, Moving, PendingClock
from support.workspace import Workspace
from textual import events
from textual.pilot import _get_mouse_message_arguments
from textual.widgets import Button, Static
from textual.worker import Worker, WorkerState

from toad.client.connection import FailedObservation, UnselectedRoute
from toad.core.events import TeamHudChanged
from toad.qt.team_board_screen import QtTeamBoardScreen
from toad.screens.team import (
    HudError,
    HudRows,
    TeamActionButton,
    TeamAlarm,
    TeamFrameView,
    TeamGroup,
    TeamPage,
    TeamTable,
)
from toad.widgets.declared_disclosure import DeclaredDisclosure
from toad.widgets.declared_table import EmptyTableSelection, SelectedTableRecord


def selected(record: HudRecord) -> SelectedTableRecord[HudRecord]:
    return SelectedTableRecord(DisclosureText.describe(record).sequence_key, record)


def with_board_action(hud: TeamHud) -> tuple[TeamHud, TeamVerbActionOffer]:
    offer = TeamVerbActionOffer(
        judge.PromoteVerb,
        ("--problem", "P1"),
        TextDigest.of("board source"),
        hud.teammate,
    )
    ping = RulePing(
        ServicePassFailing,
        offer.observation,
        text="Apply the retained board fix",
        offers=(offer,),
    )
    packet = TeamUpdateNotice(hud.teammate, (ping,))
    return replace(hud, packets=(packet,)), offer


def row_maps_cohere(table: TeamTable) -> bool:
    return (set(table.records) == set(table.entity_keys.values()) == {row.key for row in table.ordered_rows}
            and all(table.records[native].key == entity for entity, native in table.entity_keys.items()))


def published_hud() -> TeamHud:
    unit = Teammate(
        RecordedThreadIncarnation("hud-worker", 2.0), Detached,
        PendingClock(1.0, 1.0), (), 1, (), (),
    )
    return TeamHud(
        teammate=RecordedThreadIncarnation("claude-code", 1.0), units=(unit,), phases=(),
        load=OverloadDegradation.from_orders((), 0, 0),
        forks=(RecordedThreadIncarnation("fork-hud", 2.0),),
        usage=CodexUsage(UnreadableUsage(reason="not requested")), open_pings=(),
    )


async def test_team_page_survives_unreadable_frames_and_recovers(workspace: Workspace) -> None:
    hud = published_hud()
    unit, = hud.units
    TeamBoardPublicationStore.replace_all(workspace.comms.root, TeamPlan(), (hud,))
    frame, = TeamBoardPublicationStore.matching_in(workspace.comms.root)
    written = json.loads(frame.read_text())
    unreadable = json.dumps({**written, "field_from_a_newer_build": []})
    frame.write_text(unreadable)
    async with workspace.app() as ui:
        app, pilot = ui.textual
        page = TeamPage()
        await app.push_screen(page)
        notice = page.query_one(HudError)
        await ui.until(lambda: notice.display, why="the unreadable frame to reach the page")
        assert "field_from_a_newer_build" in str(notice.render())
        rows = page.query_one(HudRows)
        assert [str(row.render()) for row in rows.query(Static)] == [
            "Waiting for the team heartbeat.",
        ]

        TeamBoardPublicationStore.replace_all(workspace.comms.root, TeamPlan(), (hud,))
        await ui.until_shows("Board for claude-code")
        assert not notice.display
        last_good = tuple(rows.children)
        view = rows.query_one(TeamFrameView)
        await ui.until(lambda: bool(view.query(TeamTable)), why="the grouped native table to mount")
        table = view.query_one(TeamTable)
        await ui.until(lambda: table.selected == selected(unit), why="the actual unit to acquire a native row")
        assert all(not cell.style for key in table.entity_keys.values()
                   for cell in table.get_row(key))
        table.focus()
        await pilot.press("enter")
        await ui.until(lambda: " ".join(Detached.action.split()) in " ".join(" ".join(strip.text for strip in table.render_lines(table.size.region)).split()),
                       why="the complete action across wrapped table rows")
        # There is no registered unit behind this published fixture. Its real
        # original-detail refusal must remain visible while observation recovers.
        await ui.until_shows("Could not read the records behind")
        assert str(view.heading.render()) == "Board for claude-code"
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
        group = table.query_ancestor(TeamGroup)
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
        TeamBoardPublicationStore.replace_all(workspace.comms.root, TeamPlan(), (repaired,))
        await ui.until(lambda: view.details.selection == selected(repaired.units[0]),
                       why="changed strikes to invalidate the real selected card")
        await ui.until(lambda: len([event for event in events if event.state is WorkerState.PENDING]) == 1,
                       why="one new original-detail worker for the changed card")
        await ui.until_shows("Could not read the records behind")
        assert not notice.display
        assert rows.query_one(TeamFrameView) is view
        assert view.query_one(TeamTable) is table and table.has_focus
        # The table takes the repaired record when it reconciles its rows, after the details do.
        await ui.until(lambda: table.selected == selected(repaired.units[0]),
                       why="the table to reconcile the repaired record")
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
        failed.observe_team(ObserveTeamHud())
        await ui.until(lambda: notice.display, why="the observer failure notice")
        assert str(notice.render()) == "Team rows unavailable: observer process exited"
        assert tuple(rows.children) == recovered_rows
        await pilot.press("escape")
        await ui.step()
        assert app.screen is not page


async def test_thirty_team_board_wheels_move_only_down(workspace: Workspace) -> None:
    hud = published_hud()
    huds = tuple(
        replace(
            hud,
            teammate=RecordedThreadIncarnation(f"wheel-{index:02}", 10.0 + index),
        )
        for index in range(40)
    )
    TeamBoardPublicationStore.replace_all(workspace.comms.root, TeamPlan(), huds)
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        page = TeamPage()
        await app.push_screen(page)
        rows = page.query_one(HudRows)
        await ui.until(lambda: rows.max_scroll_y > 0, why="the fixed team board to overflow")
        arguments = _get_mouse_message_arguments(
            rows, (3, 3), button=0, shift=False, meta=False, control=False,
        )
        offsets = [float(rows.scroll_y)]
        for _ in range(30):
            await app._post_message_and_wait(events.MouseScrollDown(**arguments))
            await ui.step()
            offsets.append(float(rows.scroll_y))
        assert offsets[-1] > offsets[0]
        assert offsets == sorted(offsets)


async def test_visible_team_pages_share_exact_recipient_interest(workspace: Workspace) -> None:
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        first = TeamPage("first")
        await app.push_screen(first)
        access = app.coordination_access
        assert access.team_interest == ObserveTeamHud(NamedTeamBoards(frozenset(("first",))))
        second = TeamPage("second")
        await app.push_screen(second)
        assert access.team_interest == ObserveTeamHud(NamedTeamBoards(frozenset(("first", "second"))))
        full = TeamPage()
        await app.push_screen(full)
        assert access.team_interest == ObserveTeamHud(AllTeamBoards())
        await app.pop_screen()
        await ui.step()
        assert access.team_interest == ObserveTeamHud(NamedTeamBoards(frozenset(("first", "second"))))
        await app.pop_screen()
        await ui.step()
        assert access.team_interest == ObserveTeamHud(NamedTeamBoards(frozenset(("first",))))
        await app.pop_screen()
        await ui.step()
        assert access.team_interest == StopTeamHud()


async def test_a_heartbeat_with_no_frames_still_says_it_is_waiting(workspace: Workspace) -> None:
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        page = TeamPage()
        await app.push_screen(page)
        await ui.step()
        app.coordination_access.events.publish(TeamHudChanged(TeamBoardCut()))
        await ui.step()
        rows = page.query_one(HudRows).query(Static)
        assert [str(row.render()) for row in rows] == ["Waiting for the team heartbeat."]


async def test_a_refresh_right_after_a_key_keeps_the_key(workspace: Workspace) -> None:
    hud = published_hud()
    first, = hud.units
    second = replace(first, unit=RecordedThreadIncarnation("second-worker", 3.0))
    TeamBoardPublicationStore.replace_all(workspace.comms.root, TeamPlan(), (replace(hud, units=(first, second)),))
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        page = TeamPage()
        await app.push_screen(page)
        await ui.until(lambda: bool(page.query(TeamTable)), why="the native table to mount")
        view = page.query_one(TeamFrameView)
        table = view.query_one(TeamTable)
        await ui.until(lambda: table.row_count == 2, why="both records to acquire native rows")
        await ui.step()
        table.focus()
        await ui.until(lambda: table.has_focus, why="the table to take focus")
        table.move_cursor(row=1, animate=False)
        table.reconcile_source()  # Before the highlight reaches the frame, as a heartbeat can.
        await ui.until(lambda: view.selected == selected(second), why="the key's record to stay selected")
        assert table.selected == selected(second)


async def test_one_recipient_delta_preserves_textual_and_qt_view_identity(workspace: Workspace, monkeypatch) -> None:
    first, offer = with_board_action(published_hud())
    second = replace(first, teammate=RecordedThreadIncarnation("other", 4.0))
    initial = TeamBoardCut((first, second), frozenset((first.teammate, second.teammate)))
    changed = replace(first, units=())
    update = TeamBoardCut((changed, second), frozenset((first.teammate,)))
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        page = TeamPage()
        await app.push_screen(page)
        await ui.step()
        app.coordination_access.events.publish(TeamHudChanged(initial))
        await ui.until(lambda: len(page.rows) == 2, why="both teammate views to mount")
        changed_view = page.rows[first.teammate]
        unchanged_view = page.rows[second.teammate]
        action_button = changed_view.actions.query_one(TeamActionButton)
        assert str(action_button.label) == offer.label
        await ui.until(
            lambda: bool(unchanged_view.query(TeamTable)),
            why="the unchanged recipient table to mount",
        )
        unchanged_table = unchanged_view.query_one(TeamTable)
        unchanged_table.focus()
        await ui.until(lambda: unchanged_table.has_focus, why="the unchanged table to focus")
        selected_before = unchanged_table.selected
        app.coordination_access.events.publish(TeamHudChanged(update))
        await ui.until(lambda: page.rows[first.teammate].hud == changed, why="the changed recipient to update")
        assert page.rows[first.teammate] is changed_view
        assert page.rows[second.teammate] is unchanged_view
        assert changed_view.actions.query_one(TeamActionButton) is action_button
        assert unchanged_view.query_one(TeamTable) is unchanged_table
        assert unchanged_table.has_focus and unchanged_table.selected == selected_before
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    qt = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.coordination_access = app.coordination_access
    screen = QtTeamBoardScreen(parent)
    screen._on_hud_changed(TeamHudChanged(initial))
    changed_tab = screen.members[first.teammate]
    unchanged_tab = screen.members[second.teammate]
    action_button = changed_tab.action_buttons[offer]
    screen.tabs.setCurrentWidget(unchanged_tab)
    screen._on_hud_changed(TeamHudChanged(update))
    assert screen.members[first.teammate] is changed_tab
    assert screen.members[second.teammate] is unchanged_tab
    assert changed_tab.action_buttons[offer] is action_button
    assert screen.tabs.currentWidget() is unchanged_tab
    assert changed_tab.hud == changed and unchanged_tab.hud == second
    screen.close()
    parent.close()
    qt.quit()


async def test_selection_survives_filter_clear_refill_group_move_and_resize(workspace: Workspace) -> None:
    hud = published_hud()
    first, = hud.units
    second = replace(first, unit=RecordedThreadIncarnation("second-worker", 3.0))
    hud = replace(hud, units=(first, second))
    TeamBoardPublicationStore.replace_all(workspace.comms.root, TeamPlan(), (hud,))
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        page = TeamPage()
        await app.push_screen(page)
        await ui.until(lambda: bool(page.query(TeamTable)), why="the native table to mount")
        view = page.query_one(TeamFrameView)
        table = view.query_one(TeamTable)
        await ui.until(lambda: table.row_count == 2, why="both original records to acquire native rows")
        await ui.step()  # The mount's resize reconcile restores the frame's selection over an earlier move.
        table.focus()
        table.move_cursor(row=1, animate=False)
        await ui.until(lambda: view.selected == selected(second), why="the highlighted second record")
        semantic = view.selected.key
        before_keys = tuple(table.entity_keys.values())
        assert set(table.records) == set(before_keys) and row_maps_cohere(table)

        await ui.resize(sum(table.source.minimums), 40)  # A terminal narrower than the columns' own minimums.
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
        await ui.until(lambda: all(native.row_count == 0 for native in view.query(TeamTable)),
                       why="the native rows to clear too")
        assert all(not native.records and not native.entity_keys for native in view.query(TeamTable))
        view.filter.value = ""
        await ui.until(lambda: view.selected == selected(first), why="clear-and-refill to choose the first visible record")
        await ui.until(lambda: table.row_count == 2, why="the public native rows to refill")
        await ui.step()  # The same queued reconcile as above, after the refill.
        table.focus()
        table.move_cursor(row=1, animate=False)
        await ui.until(lambda: view.selected == selected(second), why="the second semantic identity to be selected again")
        moved = replace(second, state=Moving)
        TeamBoardPublicationStore.replace_all(workspace.comms.root, TeamPlan(), (replace(hud, units=(first, moved)),))
        await ui.until(lambda: view.selected == selected(moved), why="the original selection to move between groups")
        await ui.until(lambda: any(native.selected == selected(moved) for native in view.query(TeamTable)),
                       why="the target group to resolve the same semantic key")
        assert view.selected.key == semantic
        await ui.until(lambda: any(native.has_focus and native.selected == selected(moved)
                                   for native in view.query(TeamTable)),
                       why="native focus to follow its selected semantic record", seconds=2)
        assert view.details.selection == selected(moved)
        assert all(row_maps_cohere(native) for native in view.query(TeamTable))
        TeamBoardPublicationStore.replace_all(workspace.comms.root, TeamPlan(), (replace(hud, units=()),))
        await ui.until(lambda: view.selected == EmptyTableSelection(), why="an actually empty frame")
        TeamBoardPublicationStore.replace_all(workspace.comms.root, TeamPlan(), (hud,))
        await ui.until(lambda: view.selected == selected(first), why="a later frame to refill the original records")


async def test_core_summaries_and_alarm_ages_reach_native_disclosures(workspace: Workspace) -> None:
    hud = published_hud()
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        for value in (hud.units[0].strikes, Teammate, Detached):
            disclosed = DisclosureText.describe(value)
            disclosure = DeclaredDisclosure(DisclosureEntry(RecordKey(type(value)), "Original", disclosed))
            await app.screen.mount(disclosure)
            disclosure.collapsed = False
            await ui.until(lambda: disclosure.body.display, why="the scalar/class/family body to expand")
            assert str(disclosure.body.render()) == disclosed.summary
            assert disclosed.summary in str(disclosure.title)
        assert DisclosureText.describe(Detached).summary == Detached.display_label()
        assert not str(disclosure.body.render()).startswith("<class ")

        source = DisclosureText.describe(hud.units[0])
        assert isinstance(source, StructuredText)
        entry = DisclosureEntry(RecordKey(Teammate), "Original unit", source)
        original = DeclaredDisclosure(entry)
        await app.screen.mount(original)
        original.collapsed = False
        await ui.until(lambda: set(original.rows) == {child.key for child in source.children},
                       why="native branches to borrow Core's complete prepared children")
        before = original.rows
        assert all(before[child.key].entry is child for child in source.children)
        original.present(entry)
        await ui.until(lambda: all(original.rows[key] is row for key, row in before.items()),
                       why="presenting the same source to preserve its native child widgets")
        changed = replace(hud.units[0], strikes=hud.units[0].strikes + 1)
        original.present(DisclosureEntry(entry.key, entry.label, DisclosureText.describe(changed)))
        strikes = FieldKey(Teammate, "strikes")
        await ui.until(lambda: original.rows[strikes].entry.value.value == changed.strikes,
                       why="an original detail field to update even when its identity summary is equal")
        assert original.rows[strikes] is before[strikes]

        ping = replace(RulePing.capture(ServicePassFailing(
            watch="native-alarm", since=1000, error="original error", failed_at=1000)),
                       since=RecordedEventTime(1000))
        section = AlarmSection(NewAlarms, (ping,))
        alarm = TeamAlarm(NewAlarms)
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
