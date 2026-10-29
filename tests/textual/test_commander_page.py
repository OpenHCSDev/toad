"""Textual-facing: declared commander rows survive refresh and source failures."""

import json
from dataclasses import replace

from agent_comms.commander.vibe_check import OverloadDegradation
from agent_comms.commander_hud import (
    CommanderFrame, CommanderHud, CommanderOrder, CommanderUnit, CodexUsage, UnreadableUsage,
)
from agent_comms.field_codec import FieldCodec, OrderId
from agent_comms.thread_identity import RecordedThreadIncarnation
from agent_comms.todos import NoCommitProgress
from agent_comms.ui_model.observation import ObserveCommanderHud
from agent_comms.ui_model.unit_state import (
    AwaitingApplicationRun, Blocked, Detached, Idle, Moving, PendingClock, UnitState, Unreadable,
)
from textual.widgets import Static
from ui_theme.scheme import (
    AccentColour, ErrorColour, ForegroundMutedColour, SuccessColour, WarningColour,
)

from toad.comms_root import FailedObservation, UnselectedRoute
from toad.core.events import CommanderHudChanged
from toad.screens.commander import CommanderFrameView, CommanderPage, CommanderTable, UnitTone


async def test_commander_page_survives_unreadable_frames_and_recovers(workspace):
    order = CommanderOrder(
        "P927", "Make the commander readable", OrderId("123456789abc"),
        "pending", NoCommitProgress(), (), 0, 0,
    )
    units = tuple(
        CommanderUnit(
            RecordedThreadIncarnation(f"hud-worker-{state.declared_name}", float(index + 2)),
            state, PendingClock(1.0, 1.0),
            (order, replace(order, problem="P928", order=OrderId("23456789abcd"))),
            1, (), (),
        )
        for index, state in enumerate(UnitState.members_with(UnitState))
    )
    hud = CommanderHud(
        RecordedThreadIncarnation("claude-code", 1.0), units, (),
        OverloadDegradation.from_orders((), 0, 0),
        (RecordedThreadIncarnation("fork-hud", 200.0),),
        CodexUsage(UnreadableUsage(reason="not requested")),
    )
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
        view = rows.query_one(CommanderFrameView)
        table = view.query_one(CommanderTable)
        await ui.until(lambda: table.row_count == len(units), why="the declared table to receive units")
        assert not notice.display
        last_good = tuple(rows.children)
        names = tuple(plan.name for plan in FieldCodec.field_plans(CommanderUnit)
                      if plan.records and not plan.excluded_in("hud"))
        assert tuple(key.value for key in table.columns) == (
            *names, *FieldCodec.projections(CommanderUnit, "hud"),
        )
        assert [column.label.plain for column in table.ordered_columns] == [
            "Unit", "State", "Work", "Change", "Next",
        ]
        assert UnitTone.of(Blocked) is ErrorColour
        assert UnitTone.of(Unreadable) is ErrorColour
        assert UnitTone.of(Detached) is WarningColour
        assert UnitTone.of(AwaitingApplicationRun) is AccentColour
        assert UnitTone.of(Moving) is SuccessColour
        assert UnitTone.of(Idle) is ForegroundMutedColour
        for key, card in table.records.items():
            assert table.get_cell(key, "unit").plain == card.unit.name
            state = table.get_cell(key, "state")
            assert state.plain == card.state.declared_name
            assert state.spans[-1].style.background == app.colours.colour(UnitTone.of(card.state))
            assert table.get_cell(key, "work").plain == "P927 pending\nP928 pending"
            assert table.rows[key].height > 1
        moving = next(key for key, card in table.records.items() if card.state is Moving)
        table.move_cursor(row=table.get_row_index(moving))
        table.focus()
        await ui.step()
        await ui.until_shows("Original details unavailable:")
        assert table.selected_key == moving
        retained_row = table.rows[moving]
        assert str(view.heading.render()) == "Commander claude-code"
        assert str(view.status.render()).startswith(str(hud.load))
        assert hud.usage.line() in str(view.footer.render())
        assert "forks: fork-hud" in str(view.footer.render())
        await pilot.resize_terminal(80, 40)
        await ui.step()
        assert sum(column.get_render_width(table) for column in table.ordered_columns) <= table.size.width
        assert table.selected_key == moving

        frame.write_text(unreadable)
        await ui.until(lambda: notice.display, why="the next unreadable frame to reach the page")
        assert "field_from_a_newer_build" in str(notice.render())
        assert tuple(rows.children) == last_good

        repaired = replace(
            hud, units=tuple(replace(unit, strikes=2) for unit in reversed(units)),
            forks=(RecordedThreadIncarnation("recovered", 201.0),),
        )
        CommanderFrame.replace_all(workspace.comms.root, (repaired,))
        await ui.until_shows("forks: recovered")
        assert not notice.display
        assert rows.query_one(CommanderFrameView) is view
        assert view.query_one(CommanderTable) is table
        assert table.selected_key == moving and table.has_focus
        assert table.rows[moving] is retained_row
        assert table.selected.strikes == 2
        assert tuple(card.unit for card in table.records.values()) == tuple(
            card.unit for card in repaired.units
        )
        view.filter.value = "hud-worker-moving"
        await ui.until(lambda: table.row_count == 1, why="the cell-text filter")
        assert table.selected_key == moving
        view.needs_hand.value = True
        await ui.until(lambda: table.row_count == 0, why="the needs-hand filter to exclude moving")
        view.filter.value = ""
        await ui.until(lambda: table.row_count == sum(card.needs_hand() for card in repaired.units),
                       why="the needs-hand filter to use Core's answer")
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


async def test_a_heartbeat_with_no_frames_still_says_it_is_waiting(workspace):
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        page = CommanderPage()
        await app.push_screen(page)
        await ui.step()
        app.coordination_access.events.publish(CommanderHudChanged(()))
        await ui.step()
        rows = page.query_one("#hud-rows").query(Static)
        assert [str(row.render()) for row in rows] == ["Waiting for the commander heartbeat."]
