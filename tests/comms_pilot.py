"""Deterministic interaction checks for native comms sessions and menus."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import ActivityState, Thread
from agent_comms.operations import wire

from toad.app import ToadApp
from toad.screens.comms import CommsScreen
from toad.screens.main import MainScreen
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.agent_response import AgentResponse
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.comms_sidebar import CommsRow
from toad.widgets.side_bar import SideBarCollapsible


def row(screen, target: str) -> CommsRow:
    return next(item for item in screen.query(CommsRow) if item.target_name == target)


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-comms-pilot-") as temporary:
        root = Path(temporary)
        project = root / "project"
        project.mkdir()
        wire_root = root / "wire"
        os.environ["AGENT_COMMS_ROOT"] = str(wire_root)

        comms = wire(wire_root)
        me = project.name
        comms.register(
            Thread(name=me, tags=frozenset({"session"}), worktree=str(project))
        )
        comms.register(
            Thread(name="peer", tags=frozenset({"test"}), worktree=str(project))
        )
        comms.send("peer", "#all", "hello from peer")
        comms.set_agent_info(
            "peer", model="openrouter/test-model", context_used=250, context_size=1000
        )
        comms.set_activity("peer", ActivityState.THINKING, "reviewing the change")

        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.theme == "ansi-dark"
            assert isinstance(app.screen, MainScreen)
            assert not app.screen.query(CommsChatView)
            assert app.session_tracker.session_count == 1
            plan_panel = app.screen.query_one("#plan-panel", SideBarCollapsible)
            assert plan_panel.collapsed
            await pilot.click("#plan-panel CollapsibleTitle")
            await pilot.pause()
            assert not plan_panel.collapsed
            await pilot.click("#plan-panel CollapsibleTitle")
            await pilot.pause()
            assert plan_panel.collapsed

            await pilot.click(row(app.screen, "peer"), button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            assert [item.action for item in app.screen.query(ContextMenuItem)] == [
                "fork",
                "stop",
                "ack",
                "copy",
            ]
            await pilot.press("down", "down", "enter")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)

            assert comms.pending_count(me) == 1
            await pilot.click(row(app.screen, "#all"), button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            assert [item.action for item in app.screen.query(ContextMenuItem)] == [
                "ack",
                "copy",
            ]
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            assert comms.pending_count(me) == 0

            await pilot.click(row(app.screen, "#all"))
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen)
            assert app.screen.target == "#all"
            assert app.session_tracker.session_count == 2
            first_channel_mode = app.current_mode
            chat = app.screen.query_one(CommsChatView)
            assert chat.prompt.prompt_text_area.has_focus
            responses = list(chat.query(AgentResponse))
            assert any("hello from peer" in response.source for response in responses)
            assert any("test-model" in response.source for response in responses)
            assert chat.status == "1 active"
            chat.prompt.text = "message from pilot"
            await pilot.press("enter")
            await pilot.pause()
            assert "message from pilot" in [
                message.body for message in comms.channel_history("#all")
            ]

            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            await pilot.click(row(app.screen, "#all"))
            await pilot.pause()
            assert app.current_mode == first_channel_mode
            assert app.session_tracker.session_count == 2

            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            await pilot.click(row(app.screen, "peer"))
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen)
            assert app.screen.kind == "dm"
            assert app.session_tracker.session_count == 3

            await pilot.press("ctrl+left_square_bracket")
            await pilot.pause()
            assert app.current_mode == first_channel_mode
            await pilot.press("ctrl+right_square_bracket")
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen) and app.screen.kind == "dm"
            await pilot.press("ctrl+w")
            await pilot.pause()
            assert app.session_tracker.session_count == 2
            assert app.current_mode == first_channel_mode

            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            owner_mode = app.current_mode
            await app.close_session_mode(owner_mode)
            await pilot.pause()
            assert app.session_tracker.session_count == 0
            assert app.current_mode == "store"

    print("comms pilot: all interactions passed")


if __name__ == "__main__":
    asyncio.run(main())
