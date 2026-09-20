"""Deterministic interaction checks for native comms sessions and menus."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import ActivityState, Thread
from agent_comms.operations import wire
from textual.widgets import Input
from textual.widgets._footer import FooterKey

from toad import messages
from toad.acp import messages as acp_messages
from toad import paths
from toad.app import ToadApp
from toad.db import DB
from toad.pill import pill
from toad.screens.comms import CommsScreen
from toad.screens.main import MainScreen
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem, RenameSessionDialog
from toad.widgets.comms_sidebar import CommsRow, CommsSidebar, NewSessionButton
from toad.widgets.conversation import Loading, make_session_title
from toad.widgets.session_sidebar import SessionRow
from toad.widgets.side_bar import SideBarCollapsible
from toad.widgets.tool_call import ToolCall


def row(screen, target: str) -> CommsRow:
    return next(item for item in screen.query(CommsRow) if item.target_name == target)


async def main() -> None:
    assert pill("status", "$warning-muted", "$warning", filled=False).plain == "[status]"
    assert make_session_title("  first\n\tmessage  ") == "first message"
    assert len(make_session_title("x" * 80)) == 50
    assert make_session_title("x" * 80).endswith("…")

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
        comms.register(
            Thread(name="other-peer", tags=frozenset(), worktree=str(project))
        )
        comms.register(
            Thread(name="delete-peer", tags=frozenset(), worktree=str(project))
        )
        comms.send("peer", "#all", "hello from peer")
        comms.send("peer", me, "private from peer")
        comms.send("other-peer", me, "unrelated private message")
        comms.set_agent_info(
            "peer", model="openrouter/test-model", context_used=250, context_size=1000
        )
        comms.set_activity("peer", ActivityState.THINKING, "reviewing the change")

        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.theme == "ansi-dark"
            assert not app.has_class("-hide-thoughts")
            assert isinstance(app.screen, MainScreen)
            assert not app.screen.query(CommsChatView)
            footer_keys = list(app.screen.query(FooterKey))
            footer_actions = {key.action for key in footer_keys}
            assert any(action.endswith("toggle_irc") for action in footer_actions)
            assert not any(action.endswith("go_home") for action in footer_actions)
            assert not any(action.endswith("settings") for action in footer_actions)
            irc_key = next(
                key for key in footer_keys if key.action.endswith("toggle_irc")
            )
            await pilot.click(irc_key)
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen)
            await pilot.press("ctrl+w")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            assert app.session_tracker.session_count == 1
            session_rows = list(app.screen.query(SessionRow))
            assert len(session_rows) == 1
            assert session_rows[0].current

            owner_mode = app.current_mode
            sidebar = app.screen.query_one(CommsSidebar)
            new_session_button = sidebar.query_one(NewSessionButton)
            assert sidebar.children[0] is new_session_button
            assert new_session_button.region.height == 2
            await pilot.click(new_session_button)
            await pilot.pause()
            created_mode = app.current_mode
            assert created_mode != owner_mode
            assert app.session_tracker.session_count == 2
            assert len(list(app.screen.query(SessionRow))) == 2
            created_conversation = app.screen.conversation
            created_conversation.post_message(
                messages.UserInputSubmitted("  Name this\nfrom my first prompt  ")
            )
            await pilot.pause()
            assert (
                app.session_tracker.get_session(created_mode).title
                == "Name this from my first prompt"
            )
            created_conversation.post_message(
                messages.UserInputSubmitted("Do not rename this twice")
            )
            await pilot.pause()
            assert (
                app.session_tracker.get_session(created_mode).title
                == "Name this from my first prompt"
            )
            await app.switch_mode(owner_mode)
            await app.close_session_mode(created_mode)
            await pilot.pause()
            assert app.current_mode == owner_mode
            assert app.session_tracker.session_count == 1

            local_row = app.screen.query_one(SessionRow)
            await pilot.click(local_row, button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            assert [item.action for item in app.screen.query(ContextMenuItem)] == [
                "rename",
                "archive",
                "delete",
            ]
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, RenameSessionDialog)
            rename_input = app.screen.query_one(Input)
            rename_input.value = "Pilot session"
            await pilot.press("enter")
            await pilot.pause()
            assert app.session_tracker.get_session(owner_mode).title == "Pilot session"

            conversation = app.screen.conversation
            conversation.post_message(
                messages.UserInputSubmitted("Must not replace a manual title")
            )
            await pilot.pause()
            assert app.session_tracker.get_session(owner_mode).title == "Pilot session"

            conversation.post_message(
                acp_messages.SessionInfoUpdate("Agent-owned title")
            )
            await pilot.pause()
            assert (
                app.session_tracker.get_session(owner_mode).title == "Agent-owned title"
            )
            conversation.post_message(acp_messages.SessionInfoUpdate(None))
            await pilot.pause()
            assert app.session_tracker.get_session(owner_mode).title == ""
            assert "New Session" in app.screen.query_one(SessionRow).render().plain

            opened = await app.open_comms_session(
                owner_mode=owner_mode,
                project_path=project,
                me=me,
                target="missing-peer",
                kind="dm",
            )
            await pilot.pause()
            assert opened == owner_mode
            assert app.session_tracker.session_count == 1

            conversation._loading = await conversation.post(Loading("Thinking…"))
            conversation.post_message(
                acp_messages.Thinking("agent_thought_chunk", "Inspecting the workspace")
            )
            await pilot.pause()
            thought = conversation.query_one(AgentThought)
            assert "Inspecting the workspace" in thought.source
            assert thought.display and thought.region.height > 0
            assert conversation._loading is None

            conversation.post_message(
                acp_messages.ToolCall(
                    {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "pilot-tool",
                        "title": "Run tests",
                        "kind": "execute",
                        "status": "in_progress",
                    }
                )
            )
            await pilot.pause()
            tool = conversation.query_one(ToolCall)
            assert "Run tests" in tool.tool_call_header_content.plain
            assert "running" in tool.tool_call_header_content.plain
            assert app.session_tracker.get_session(owner_mode).summary == "Run tests"
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
                "archive",
                "delete",
                "ack",
                "copy",
            ]
            await pilot.press("down", "down", "down", "down", "enter")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            assert comms.pending_count(me, "peer") == 0
            assert comms.pending_count(me, "other-peer") == 1
            assert comms.pending_count(me, "#all") == 1

            assert comms.pending_count(me) == 2
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
            assert comms.pending_count(me, "#all") == 0
            assert comms.pending_count(me, "other-peer") == 1
            assert comms.pending_count(me) == 1

            await pilot.click(row(app.screen, "other-peer"), button=3)
            await pilot.pause()
            stop_item = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == "stop"
            )
            await pilot.click(stop_item)
            await pilot.pause()
            assert comms.thread_detail("other-peer")["status"] == "stopped"
            await pilot.click(row(app.screen, "other-peer"), button=3)
            await pilot.pause()
            archive_item = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == "archive"
            )
            await pilot.click(archive_item)
            await pilot.pause()
            assert comms.registry.status("other-peer").value == "archived"
            assert not any(
                item.target_name == "other-peer" for item in app.screen.query(CommsRow)
            )

            await pilot.click(row(app.screen, "delete-peer"), button=3)
            await pilot.pause()
            stop_item = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == "stop"
            )
            await pilot.click(stop_item)
            await pilot.pause()
            await pilot.click(row(app.screen, "delete-peer"), button=3)
            await pilot.pause()
            delete_item = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == "delete"
            )
            await pilot.click(delete_item)
            await pilot.pause()
            assert "delete-peer" not in comms.registry
            assert not any(
                item.target_name == "delete-peer"
                for item in app.screen.query(CommsRow)
            )

            await pilot.click(row(app.screen, "#all"))
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen)
            assert app.screen.target == "#all"
            assert app.session_tracker.session_count == 2
            assert len(list(app.screen.query(SessionRow))) == 2
            owner_screen = app.get_screen_stack(owner_mode)[-1]
            assert len(list(owner_screen.query(SessionRow))) == 2
            first_channel_mode = app.current_mode
            chat = app.screen.query_one(CommsChatView)
            assert chat.prompt.prompt_text_area.has_focus
            responses = list(chat.query(AgentResponse))
            assert any("hello from peer" in response.source for response in responses)
            assert not any("private" in response.source for response in responses)
            assert any("test-model" in response.source for response in responses)
            assert chat.status == "1 active"
            chat.prompt.text = "message from pilot"
            await pilot.press("enter")
            await pilot.pause()
            assert "message from pilot" in [
                message.body for message in comms.channel_history("#all")
            ]

            owner_row = next(
                item
                for item in app.screen.query(SessionRow)
                if item.mode_name == owner_mode
            )
            await pilot.click(owner_row)
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
            owner_row = next(
                item
                for item in app.screen.query(SessionRow)
                if item.mode_name == owner_mode
            )
            await pilot.click(owner_row, button=3)
            await pilot.pause()
            await pilot.press("down", "enter")
            await pilot.pause()
            assert app.session_tracker.session_count == 0
            assert app.current_mode == "store"

            state_path = root / "state"
            state_path.mkdir()
            paths.get_state = lambda: state_path
            await app.new_session_screen(app.get_main_screen)
            await pilot.pause()
            delete_mode = app.current_mode
            saved_db = DB()
            assert await saved_db.create()
            saved_pk = await saved_db.session_new(
                "Delete me",
                "Pilot agent",
                "pilot-agent",
                "pilot-session",
            )
            assert saved_pk is not None
            app.screen._session_pk = saved_pk
            delete_row = next(
                item
                for item in app.screen.query(SessionRow)
                if item.mode_name == delete_mode
            )
            await pilot.click(delete_row, button=3)
            await pilot.pause()
            await pilot.press("down", "down", "enter")
            await pilot.pause()
            assert app.session_tracker.session_count == 0
            assert app.current_mode == "store"
            assert await saved_db.session_get(saved_pk) is None

    print("comms pilot: all interactions passed")


if __name__ == "__main__":
    asyncio.run(main())
