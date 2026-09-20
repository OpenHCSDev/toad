"""Deterministic interaction checks for native comms sessions and menus."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from agent_comms import ActivityState, Thread
from agent_comms.operations import wire
from textual.content import Content
from textual.widgets import Footer, Input, Markdown, Tabs
from textual.widgets._footer import FooterKey

from toad import messages
from toad.acp.agent import Agent as ACPAgent
from toad.acp import messages as acp_messages
from toad import paths
from toad.app import ToadApp
from toad.db import DB
from toad.pill import pill
from toad.screens.comms import CommsScreen
from toad.screens.main import MainScreen
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.comms_chat import (
    HISTORY_PAGE_SIZE,
    HISTORY_WINDOW_SIZE,
    CommsChatView,
)
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem, RenameSessionDialog
from toad.widgets.comms_sidebar import (
    CoordinationStatus,
    CommsRow,
    CommsSidebar,
    NewSessionButton,
)
from toad.widgets.conversation import Loading, make_session_title
from toad.widgets.flash import Flash
from toad.widgets.session_sidebar import SessionRow
from toad.widgets.session_tabs import SessionLabel, SessionsTabs
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SideBarToggle
from toad.widgets.throbber import Throbber
from toad.widgets.tool_call import ToolCall
from toad.widgets.project_panel import FilePreview, ProjectSearchButton


def row(screen, target: str) -> CommsRow:
    return next(item for item in screen.query(CommsRow) if item.target_name == target)


async def main() -> None:
    assert (
        pill("status", "$warning-muted", "$warning", filled=False).plain == "[status]"
    )
    assert make_session_title("  first\n\tmessage  ") == "first message"
    assert len(make_session_title("x" * 80)) == 50
    assert make_session_title("x" * 80).endswith("…")

    with tempfile.TemporaryDirectory(prefix="toad-comms-pilot-") as temporary:
        root = Path(temporary)
        project = root / "project"
        project.mkdir()
        preview_path = project / "README.md"
        preview_path.write_text("# Preview\n\nRendered markdown.")
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
        for index in range(HISTORY_WINDOW_SIZE * 2):
            comms.send("peer", "#test", f"long history {index:03}")
        comms.acknowledge(me, "#test")
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
            assert all(
                key.get_component_rich_style("footer-key--key").reverse
                for key in footer_keys
            )
            assert any(action.endswith("toggle_irc") for action in footer_actions)
            assert not any(action.endswith("go_home") for action in footer_actions)
            assert not any(action.endswith("settings") for action in footer_actions)
            irc_key = next(
                key for key in footer_keys if key.action.endswith("toggle_irc")
            )
            session_label = app.screen.query_one(SessionLabel)
            assert await pilot.hover(session_label)
            assert session_label.rich_style.reverse
            info_bar = app.screen.query_one("#info-container")
            footer = app.screen.query_one(Footer)
            assert info_bar.region.bottom == footer.region.y
            throbber = app.screen.conversation.query_one(Throbber)
            throbber.add_class("-busy")
            await pilot.pause()
            assert throbber.region.bottom == app.screen.conversation.prompt.region.y, (
                throbber.region,
                app.screen.conversation.prompt.region,
            )
            throbber.remove_class("-busy")
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
            assert await pilot.hover(session_rows[0])
            assert (
                session_rows[0].rich_style.color != session_rows[0].rich_style.bgcolor
            )
            coordination = app.screen.query_one(CoordinationStatus)
            assert "persistent" in coordination.render().plain
            assert str(wire_root) in str(coordination.tooltip)
            shell_sidebar = app.screen.query_one(SideBar)
            panels = list(shell_sidebar.query(SideBarCollapsible))
            assert all(
                panel.region.height <= 2 for panel in panels if panel.collapsed
            ), [(panel.title, panel.collapsed, panel.region.height) for panel in panels]
            assert panels[0].region.height < shell_sidebar.region.height
            sidebar_toggle = shell_sidebar.query_one(SideBarToggle)
            assert sidebar_toggle.region.width == 1
            assert sidebar_toggle.region.height == shell_sidebar.region.height
            await pilot.click(sidebar_toggle)
            await pilot.pause()
            assert shell_sidebar.collapsed
            assert shell_sidebar.region.width == 1
            assert shell_sidebar.content_region.width == 1
            assert shell_sidebar.render() == ">"
            assert sidebar_toggle.tooltip == "Expand sidebar"
            await pilot.hover(app.screen.conversation.prompt)
            collapsed_background = sidebar_toggle.styles.background
            assert await pilot.hover(sidebar_toggle)
            await pilot.pause()
            assert sidebar_toggle.styles.background != collapsed_background
            await pilot.click(sidebar_toggle)
            await pilot.pause()
            assert not shell_sidebar.collapsed
            assert shell_sidebar.region.width == 40
            assert sidebar_toggle.tooltip == "Collapse sidebar"

            await app.screen.open_file_preview(preview_path)
            await pilot.pause()
            workspace_tabs = app.screen.query_one("#workspace-tabs", Tabs)
            assert workspace_tabs.has_class("-has-preview")
            assert workspace_tabs.active.startswith("preview-tab-")
            assert app.screen.query_one(FilePreview).query_one(Markdown)
            app.screen._show_conversation_view()
            search_button = app.screen.query_one(ProjectSearchButton)
            search_button.action_search()
            await pilot.pause()
            assert app.screen.conversation.prompt.show_path_search
            app.screen.conversation.prompt.show_path_search = False

            owner_mode = app.current_mode
            sidebar = app.screen.query_one(CommsSidebar)
            new_session_button = sidebar.query_one(NewSessionButton)
            assert sidebar.children[0] is new_session_button
            assert new_session_button.region.height == 1
            assert await pilot.hover(new_session_button)
            assert (
                new_session_button.rich_style.color
                != new_session_button.rich_style.bgcolor
            )
            await pilot.click(new_session_button)
            await pilot.pause()
            created_mode = app.current_mode
            assert created_mode != owner_mode
            assert app.session_tracker.session_count == 2
            assert len(list(app.screen.query(SessionRow))) == 2
            created_conversation = app.screen.conversation
            assert app.session_tracker.get_session(created_mode).title == "New Session"
            managed_thread = "managed-test-thread"
            comms.register(
                Thread(
                    name=managed_thread,
                    tags=frozenset({"acp"}),
                    worktree=str(project),
                    pid=os.getpid(),
                )
            )
            startup_agent = object.__new__(ACPAgent)
            startup_agent._message_target = created_conversation
            startup_agent._pending_session_name = None
            startup_agent._process = SimpleNamespace(pid=os.getpid())
            startup_agent.session_pk = None
            startup_agent._publish_coordination_metadata(
                {
                    "_meta": {
                        "agentComms": {
                            "thread": managed_thread,
                            "wireRoot": str(wire_root),
                            "persistence": "shared on-disk wire",
                            "transport": "per-session stdio ACP",
                        }
                    }
                }
            )
            await pilot.pause()
            assert app.session_tracker.get_session(created_mode).title == "New Session"
            await startup_agent.set_session_name("Name this from my first prompt")
            created_conversation.post_message(
                messages.SessionUpdate(name="Name this from my first prompt")
            )
            await pilot.pause()
            renamed_thread = "Name-this-from-my-first-prompt"
            assert comms.registry.require(managed_thread).name == renamed_thread
            assert app.screen._session_thread == renamed_thread
            assert (
                renamed_thread
                in app.screen.query_one(CoordinationStatus).render().plain
            )
            visible_targets = {item.target_name for item in app.screen.query(CommsRow)}
            assert not {managed_thread, renamed_thread} & visible_targets
            assert (
                app.session_tracker.get_session(created_mode).title
                == "Name this from my first prompt"
            )
            startup_agent.rpc_session_update(
                sessionId=managed_thread,
                update={
                    "sessionUpdate": "session_info_update",
                    "title": renamed_thread,
                },
            )
            await pilot.pause()
            assert (
                app.session_tracker.get_session(created_mode).title
                == "Name this from my first prompt"
            )
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
            created_sidebar = app.screen.query_one(SideBar)
            created_sidebar.toggle()
            await pilot.pause()
            assert created_sidebar.collapsed
            assert app.settings.get("sidebar.hide", bool)
            await app.switch_mode(owner_mode)
            await pilot.pause()
            assert app.screen.query_one(SideBar).collapsed
            await app.switch_mode(created_mode)
            await pilot.pause()
            assert app.screen.query_one(SideBar).collapsed
            app.screen.query_one(SideBar).reveal()
            await pilot.pause()
            assert not app.settings.get("sidebar.hide", bool)
            stopped_agents = 0

            class ClosingAgent:
                def get_info(self) -> Content:
                    return Content("test")

                async def stop(self) -> None:
                    nonlocal stopped_agents
                    stopped_agents += 1

            created_conversation.agent = ClosingAgent()
            await app.switch_mode(owner_mode)
            await app.close_session_mode(created_mode)
            await pilot.pause()
            assert app.current_mode == owner_mode
            assert app.session_tracker.session_count == 1
            assert stopped_agents == 1

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
            flash = conversation.query_one(Flash)
            flash.flash("Readable notification", duration=10, style="warning")
            await pilot.pause()
            assert flash.visible
            assert flash.rich_style.color != flash.rich_style.bgcolor
            flash.visible = False
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
            current_summary = app.session_tracker.get_session(owner_mode).summary
            conversation.turn = "client"
            conversation.post_message(acp_messages.Update("text", "Background message"))
            await pilot.pause()
            assert (
                app.session_tracker.get_session(owner_mode).summary == current_summary
            )
            conversation.turn = "agent"
            conversation.post_message(acp_messages.Update("text", "Finished answer"))
            await pilot.pause()
            assert (
                app.session_tracker.get_session(owner_mode).summary
                == "Writing response"
            )
            protocol_agent = object.__new__(ACPAgent)
            protocol_agent._message_target = conversation
            protocol_agent.rpc_session_update(
                "pilot-session",
                {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": ""},
                    "_meta": {"agentComms": {"turnSettled": True}},
                },
            )
            await pilot.pause()
            settled = app.session_tracker.get_session(owner_mode)
            assert settled.state == "idle"
            assert settled.summary == "Ready for review"
            conversation.post_message(
                acp_messages.Thinking("agent_thought_chunk", "Inspecting the workspace")
            )
            await pilot.pause()
            thought = conversation.query_one(AgentThought)
            assert "Inspecting the workspace" in thought.source
            assert thought.display and thought.region.height > 0
            assert conversation._loading is None

            class SlowCancelAgent:
                def __init__(self) -> None:
                    self.called = asyncio.Event()
                    self.release = asyncio.Event()

                async def cancel(self) -> bool:
                    self.called.set()
                    await self.release.wait()
                    return True

                def get_info(self):
                    return "test agent"

                async def stop(self) -> None:
                    return None

            original_agent = conversation.agent
            cancel_agent = SlowCancelAgent()
            conversation.agent = cancel_agent
            conversation.turn = "agent"
            conversation._last_escape_time = 0.0
            conversation._loading = await conversation.post(Loading("Thinking…"))
            conversation.action_cancel()
            await pilot.pause()
            assert not cancel_agent.called.is_set()
            conversation.action_cancel()
            for _ in range(10):
                if cancel_agent.called.is_set():
                    break
                await pilot.pause()
            assert cancel_agent.called.is_set()
            assert conversation._loading.render().plain == "Cancelling…"
            assert conversation.turn == "agent"
            cancel_agent.release.set()
            await pilot.pause()
            if conversation._loading is not None:
                await conversation._loading.remove()
            conversation._loading = None
            conversation.agent = original_agent
            conversation.turn = "client"

            prompt_input = conversation.prompt.prompt_text_area
            prompt_input.text = "clear this entire draft"
            prompt_input.focus()
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert prompt_input.text == ""

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
                "comms_fork",
                "comms_stop",
                "comms_archive",
                "comms_delete",
                "comms_ack",
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
                "comms_ack",
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
                if item.action == "comms_stop"
            )
            await pilot.click(stop_item)
            await pilot.pause()
            assert comms.thread_detail("other-peer")["status"] == "stopped"
            await pilot.click(row(app.screen, "other-peer"), button=3)
            await pilot.pause()
            archive_item = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == "comms_archive"
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
                if item.action == "comms_stop"
            )
            await pilot.click(stop_item)
            await pilot.pause()
            await pilot.click(row(app.screen, "delete-peer"), button=3)
            await pilot.pause()
            delete_item = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == "comms_delete"
            )
            await pilot.click(delete_item)
            await pilot.pause()
            assert "delete-peer" not in comms.registry
            assert not any(
                item.target_name == "delete-peer" for item in app.screen.query(CommsRow)
            )

            await pilot.click(row(app.screen, "#all"))
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen)
            assert app.screen.target == "#all"
            assert row(app.screen, "#all").selected
            assert app.session_tracker.session_count == 1
            assert len(list(app.screen.query(SessionRow))) == 1
            owner_screen = app.get_screen_stack(owner_mode)[-1]
            assert len(list(owner_screen.query(SessionRow))) == 1
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
            assert app.session_tracker.session_count == 1

            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            await pilot.click(row(app.screen, "#test"))
            await pilot.pause()
            long_chat = app.screen.query_one(CommsChatView)
            assert len(long_chat._history) == HISTORY_PAGE_SIZE
            assert "long history 239" in long_chat._history[-1][1].source
            previous_oldest = long_chat._history[0][0].seq
            long_chat._edge_load_scheduled = True
            long_chat.window.scroll_home(animate=False)
            await pilot.pause()
            anchor = long_chat._history[0][1]
            anchor_y = anchor.region.y
            long_chat._edge_load_scheduled = False
            long_chat._on_window_scroll(long_chat.window.scroll_y)
            for _ in range(10):
                if long_chat._history[0][0].seq < previous_oldest:
                    break
                await pilot.pause()
            assert long_chat._history[0][0].seq < previous_oldest
            await pilot.pause()
            assert abs(anchor.region.y - anchor_y) <= 1
            while not long_chat._has_newer:
                page = long_chat._message_page(
                    comms, before=long_chat._history[0][0].seq
                )
                await long_chat._mount_page(page, older=True)
            sequences = [message.seq for message, _ in long_chat._history]
            assert len(sequences) == HISTORY_WINDOW_SIZE
            assert len(sequences) == len(set(sequences))
            assert sequences[0] < previous_oldest
            assert long_chat._has_newer
            newest_before = sequences[-1]
            page = long_chat._message_page(comms, after=newest_before)
            await long_chat._mount_page(page, older=False)
            assert long_chat._history[-1][0].seq > newest_before
            assert len(long_chat._history) == HISTORY_WINDOW_SIZE
            assert long_chat._has_older

            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            await pilot.click(row(app.screen, "peer"))
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen)
            assert app.screen.kind == "dm"
            assert row(app.screen, "peer").selected
            tabs = app.screen.query_one(SessionsTabs)
            assert tabs.current_session == app.current_mode
            active_tab = tabs.query_one(f"#{app.current_mode}", SessionLabel)
            assert active_tab.has_class("-current")
            assert active_tab.render().plain == "@peer"
            assert app.session_tracker.session_count == 1
            assert len(list(app.screen.query(SessionRow))) == 1
            assert not any(
                session.title == "@peer"
                for session in app.session_tracker.ordered_sessions
            )

            await pilot.click(row(app.screen, "peer"), button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            assert [item.action for item in app.screen.query(ContextMenuItem)] == [
                "comms_fork",
                "comms_stop",
                "comms_archive",
                "comms_delete",
                "comms_ack",
                "copy",
            ]
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen) and app.screen.kind == "dm"
            await pilot.press("ctrl+w")
            await pilot.pause()
            assert app.session_tracker.session_count == 1
            assert isinstance(app.screen, MainScreen)

            await pilot.click(row(app.screen, "#all"))
            await pilot.pause()
            assert app.current_mode == first_channel_mode
            await pilot.press("escape")
            await pilot.pause()
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
