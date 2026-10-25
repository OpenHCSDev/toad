"""Textual-facing: the commander page paints the HUD change Core's stream delivers."""

import json
from dataclasses import replace

from agent_comms.commander.vibe_check import OverloadDegradation
from agent_comms.commander_hud import CommanderFrame, CommanderHud, CodexUsage, UnreadableUsage
from agent_comms.thread_identity import RecordedThreadIncarnation
from textual.widgets import Static

from toad.core.events import CommanderHudChanged, CommanderHudFailed
from toad.screens.commander import CommanderPage


async def test_commander_page_survives_unreadable_frames_and_recovers(workspace):
    hud = CommanderHud(
        RecordedThreadIncarnation("claude-code", 1.0), (), (),
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
        assert [str(row.render()) for row in last_good] == [
            "Commander claude-code", str(hud.load), hud.usage.line(), "forks: fork-hud",
        ]

        frame.write_text(unreadable)
        await ui.until(lambda: notice.display, why="the next unreadable frame to reach the page")
        assert "field_from_a_newer_build" in str(notice.render())
        assert tuple(rows.children) == last_good

        repaired = replace(hud, forks=(RecordedThreadIncarnation("recovered", 3.0),))
        CommanderFrame.replace_all(workspace.comms.root, (repaired,))
        await ui.until_shows("forks: recovered")
        assert not notice.display
        recovered_rows = tuple(rows.children)
        app.coordination_access.events.publish(CommanderHudFailed(OSError("observer process exited")))
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
