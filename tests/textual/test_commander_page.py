"""Textual-facing: the commander page paints the HUD change Core's stream delivers."""

from agent_comms.commander.vibe_check import OverloadDegradation
from agent_comms.commander_hud import CommanderHud
from agent_comms.thread_identity import RecordedThreadIncarnation
from textual.widgets import Static

from toad.core.events import CommanderHudChanged
from toad.screens.commander import CommanderPage


async def test_opening_the_commander_page_renders_a_hud_change(workspace):
    hud = CommanderHud(
        RecordedThreadIncarnation("claude-code", 1.0), (), (),
        OverloadDegradation.from_orders((), 0, 0),
    )
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        page = CommanderPage()
        await app.push_screen(page)
        await ui.step()
        app.coordination_access.events.publish(CommanderHudChanged((hud,)))
        await ui.step()
        rows = page.query_one("#hud-rows").query(Static)
        assert [str(row.render()) for row in rows][:2] == [
            "Commander claude-code", str(hud.load),
        ]


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
