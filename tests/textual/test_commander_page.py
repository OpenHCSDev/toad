"""Textual-facing: the commander page paints the HUD change Core's stream delivers."""

import json
from dataclasses import replace

from agent_comms.commander.vibe_check import OverloadDegradation
from agent_comms.commander_hud import (
    CommanderFrame, CommanderHud, CommanderUnit, CodexUsage, UnreadableUsage,
)
from agent_comms.thread_identity import RecordedThreadIncarnation
from agent_comms.ui_model.observation import ObserveCommanderHud
from agent_comms.ui_model.unit_state import Detached, PendingClock
from textual.widgets import Static
from textual.widgets._collapsible import CollapsibleTitle

from toad.comms_root import FailedObservation, UnselectedRoute
from toad.core.events import CommanderHudChanged
from toad.screens.commander import CommanderFrameView, CommanderPage, CommanderUnitCard


async def test_commander_page_survives_unreadable_frames_and_recovers(workspace):
    unit = CommanderUnit(
        RecordedThreadIncarnation("hud-worker", 2.0), Detached,
        PendingClock(1.0, 1.0), (), 1, (), (),
    )
    hud = CommanderHud(
        RecordedThreadIncarnation("claude-code", 1.0), (unit,), (),
        OverloadDegradation.from_orders((), 0, 0),
        (RecordedThreadIncarnation("fork-hud", 2.0),),
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
        assert not notice.display
        last_good = tuple(rows.children)
        view = rows.query_one(CommanderFrameView)
        card = view.query_one(CommanderUnitCard)
        assert card.collapsed
        title = card.query_one(CollapsibleTitle)
        title.focus()
        await pilot.press("enter")
        await ui.until(lambda: not card.collapsed, why="the unit card to expand by keyboard")
        await ui.until_shows(Detached.action)
        assert str(view.heading.render()) == "Commander claude-code"
        assert str(view.status.render()).startswith(str(hud.load))
        assert hud.usage.line() in str(view.footer.render())
        assert "forks: fork-hud" in str(view.footer.render())

        frame.write_text(unreadable)
        await ui.until(lambda: notice.display, why="the next unreadable frame to reach the page")
        assert "field_from_a_newer_build" in str(notice.render())
        assert tuple(rows.children) == last_good

        repaired = replace(
            hud, units=(replace(unit, strikes=2),),
            forks=(RecordedThreadIncarnation("recovered", 3.0),),
        )
        CommanderFrame.replace_all(workspace.comms.root, (repaired,))
        await ui.until_shows("forks: recovered")
        assert not notice.display
        assert rows.query_one(CommanderFrameView) is view
        assert view.query_one(CommanderUnitCard) is card
        assert not card.collapsed and title.has_focus
        assert card.card.strikes == 2
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
