"""Deterministic interaction checks for native comms sessions and menus."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from agent_comms import ActivityState, ForkSpec, Thread
from agent_comms.operations import wire
from textual.content import Content
from textual.widgets import Footer, Markdown
from textual.widgets._footer import FooterKey

from toad import messages
from toad.acp.agent import Agent as ACPAgent
from toad.acp import messages as acp_messages
from toad import paths
from runtime_fixture import ToadApp
from toad.db import DB
from toad.pill import pill
from toad.screens.comms import CommsScreen
from toad.screens.main import MainScreen
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.comms_chat import (
    INITIAL_HISTORY_PAGE_SIZE,
    HISTORY_WINDOW_SIZE,
    CommsChatView,
)
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.comms_sidebar import (
    CoordinationStatus,
    CommsRow,
    CommsSidebar,
    NewSessionButton,
)
from toad.widgets.conversation import Loading, make_session_title
from toad.widgets.flash import Flash
from toad.widgets.prompt import Prompt
from toad.widgets.session_sidebar import SessionRow
from toad.widgets.session_tabs import SessionLabel, SessionsTabs
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SideBarToggle
from toad.widgets.throbber import Throbber, ThrobberVisual
from textual.style import Style
from toad.widgets.tool_call import ToolCall
from toad.widgets.project_panel import FilePreview, ProjectSearchButton
from toad.widgets.user_input import UserInput
from toad.widgets.incoming_message import IncomingMessage, IncomingSender
from toad.widgets.irc_message import IRCMessage, ThreadLink


def row(screen, target: str) -> CommsRow:
    return next(item for item in screen.query(CommsRow) if item.target_name == target)


async def main() -> None:
    assert (
        pill("status", "$warning-muted", "$warning", filled=False).plain == "[status]"
    )
    assert make_session_title("  first\n\tmessage  ") == "first message"
    assert len(make_session_title("x" * 80)) == 50
    assert make_session_title("x" * 80).endswith("…")
    throbber_segments = ThrobberVisual(get_time=lambda: 0).make_segments(Style(), 24)
    assert {segment.style.color.number for segment in throbber_segments} == set(
        range(1, 7)
    )

    with tempfile.TemporaryDirectory(prefix="toad-comms-pilot-") as temporary:
        root = Path(temporary)
        os.environ["XDG_CONFIG_HOME"] = str(root / ".config")
        os.environ["XDG_STATE_HOME"] = str(root / ".state")
        os.environ["XDG_DATA_HOME"] = str(root / ".data")
        project = root / "project"
        project.mkdir()
        preview_path = project / "README.md"
        preview_path.write_text("# Preview\n\nRendered markdown.")
        wire_root = root / "wire"
        os.environ["AGENT_COMMS_ROOT"] = str(wire_root)
        gates = root / "backend-gates"
        gates.mkdir()
        os.environ["TOAD_TEST_GATES"] = str(gates)
        backend_stub = root / "pi-turn-state"
        backend_stub.write_text(f"#!{sys.executable}\n" + """
import json, os, sys, time
from pathlib import Path
from agent_comms.native_pi import CAPABILITY
def emit(value):
    print(json.dumps(value), flush=True)
for line in sys.stdin:
    command = json.loads(line)
    kind = command.get("type")
    if kind == "get_state":
        emit({"id": command.get("id"), "type": "response", "command": kind,
              "success": True, "data": {"nativeInputProofCapability": CAPABILITY}})
    elif kind == "prompt":
        emit({"id": command["id"], "type": "response", "command": kind, "success": True})
        emit({"type": "message_start", "message": {"role": "user", "content": command["message"], "inputId": command["inputId"]}})
        text = command["message"].splitlines()[-1]
        emit({"type": "message_update", "assistantMessageEvent": {"type": "thinking_delta", "delta": "reasoning for " + text}})
        gate = Path(os.environ["TOAD_TEST_GATES"]) / os.environ["AGENT_COMMS_THREAD"]
        while gate.exists():
            time.sleep(0.02)
        emit({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "response for " + text}})
        emit({"type": "message_end", "message": {"role": "assistant", "stopReason": "stop"}})
        emit({"type": "agent_settled"})
    else:
        emit({"id": command.get("id"), "type": "response", "command": kind, "success": True, "data": {}})
""")
        backend_stub.chmod(0o755)
        os.environ["AGENT_COMMS_AGENT_BIN"] = str(backend_stub)
        os.environ["AGENT_COMMS_AGENT_ARGS"] = ""

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
        resumable_session = root / "resumable-session.jsonl"
        resumable_session.write_text(
            "\n".join(
                json.dumps(record)
                for record in [
                    {
                        "type": "message",
                        "message": {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "thread transcript request"}
                            ],
                        },
                    },
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "thinking", "thinking": "thread reasoning"},
                                {
                                    "type": "toolCall",
                                    "id": "thread-tool",
                                    "name": "comms_send",
                                    "arguments": {"to": "peer"},
                                },
                            ],
                        },
                    },
                    {
                        "type": "message",
                        "message": {
                            "role": "toolResult",
                            "toolCallId": "thread-tool",
                            "toolName": "comms_send",
                            "content": [{"type": "text", "text": "thread tool result"}],
                            "isError": False,
                        },
                    },
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "thread transcript complete"}
                            ],
                        },
                    },
                ]
            )
        )
        comms.register(
            Thread(
                name="resumable-peer",
                tags=frozenset({"test"}),
                worktree=str(project),
                session_file=str(resumable_session),
            )
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
            assert await pilot.click(f"#close-{app.current_mode}")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            assert app.session_tracker.session_count == 1
            session_rows = list(app.screen.query(SessionRow))
            assert len(session_rows) == 1
            assert session_rows[0].current
            assert await pilot.hover(session_rows[0])
            assert (
                session_rows[0].rich_style.color != session_rows[0].rich_style.bgcolor
            ), (session_rows[0].rich_style, session_rows[0].classes, app.focused,
                app.sidebar_state, app.screen.query_one(CommsSidebar).navigation_ready.is_set())
            coordination = app.screen.query_one(CoordinationStatus)
            assert "persistent" in coordination.render().plain
            assert str(wire_root) in str(coordination.tooltip)
            shell_sidebar = app.screen.query_one(SideBar)
            panels = list(shell_sidebar.query(SideBarCollapsible))
            assert (
                panels[0].query_one("CollapsibleTitle").region.y == panels[0].region.y
            )
            conversation = app.screen.conversation
            assert conversation.prompt.region.x == conversation.region.x
            assert conversation.contents.region.x == conversation.region.x + 1
            assert all(
                panel.region.height <= 2 for panel in panels if panel.collapsed
            ), [(panel.title, panel.collapsed, panel.region.height) for panel in panels]
            assert shell_sidebar.region.bottom - panels[0].region.bottom <= 1
            await pilot.click(panels[0].query_one("CollapsibleTitle"))
            await pilot.pause()
            assert panels[0].region.height <= 2
            await pilot.click(panels[0].query_one("CollapsibleTitle"))
            thread_sidebar = app.screen.query_one("#thread-sidebar", SideBar)
            await pilot.click(thread_sidebar.query_one(SideBarToggle))
            await pilot.pause()
            assert thread_sidebar.region.x >= conversation.region.right
            thread_panels = list(thread_sidebar.query(SideBarCollapsible))
            assert [panel.title for panel in thread_panels] == ["Thread", "Comms", "Plan", "Project", "Recovery"]
            assert not thread_panels[-1].display, "Optional recovery view must remain default-off"
            project_panel = thread_panels[-2]
            await pilot.click(project_panel.query_one("CollapsibleTitle"))
            await pilot.pause()
            assert project_panel.region.height > 2
            await pilot.click(project_panel.query_one("CollapsibleTitle"))
            await pilot.pause()
            assert project_panel.region.height <= 2
            await pilot.click(thread_sidebar.query_one(SideBarToggle))
            await pilot.pause()
            assert thread_sidebar.collapsed and not shell_sidebar.collapsed
            sidebar_toggle = shell_sidebar.query_one(SideBarToggle)
            assert sidebar_toggle.region.width == 3
            assert sidebar_toggle.region.height == shell_sidebar.region.height
            assert sidebar_toggle.rich_style.bgcolor.number in {0, 8}
            await pilot.click(sidebar_toggle)
            await pilot.pause()
            assert shell_sidebar.collapsed
            assert shell_sidebar.region.width == 3
            assert shell_sidebar.content_region.width == 3
            assert sidebar_toggle.region.width == 3
            assert conversation.window.styles.padding.left == 1
            assert conversation.prompt.region.x == conversation.region.x
            assert app.screen.query_one(SessionsTabs).region.x == conversation.region.x
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
            assert conversation.window.styles.padding.left == 0
            assert sidebar_toggle.region.width == 3
            assert sidebar_toggle.tooltip == "Collapse sidebar"
            assert sidebar_toggle.rich_style.bgcolor.number in {0, 8}

            shell_sidebar.toggle()
            await pilot.pause()
            assert shell_sidebar.collapsed
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            assert not shell_sidebar.collapsed
            focused_session = app.screen.query_one(SessionRow)
            assert focused_session.has_focus
            shortcut_snapshot = app.screen.query_one(CommsSidebar)._snapshot()
            assert focused_session.has_class("-wire-thread"), (
                shortcut_snapshot.session_threads,
                shortcut_snapshot.all_people,
                app.screen._session_thread,
            )

            preview_owner_mode = app.current_mode
            await app.screen.open_file_preview(preview_path)
            await pilot.pause()
            from toad.screens.file_preview import FilePreviewScreen
            assert isinstance(app.screen, FilePreviewScreen)
            preview_mode = app.current_mode
            assert any(tab.mode_name == preview_mode for tab in app.open_tabs)
            assert app.screen.query_one(FilePreview).query_one(Markdown)
            await app.close_session_mode(preview_mode)
            assert app.current_mode == preview_owner_mode
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
            session_rows = list(app.screen.query(SessionRow))
            # An unbound local view is a tab, not a second authoritative thread.
            assert len(session_rows) == 1
            assert app.screen.query_one(f"SessionLabel#{created_mode}")
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
                    "title": "Name this from my first prompt",
                    "_meta": {"agentComms": {"thread": renamed_thread}},
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
            assert renamed_thread not in {
                item.target_name for item in app.screen.query(CommsRow)
            }
            assert len(list(app.screen.query(SessionRow))) == 2
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
            assert await pilot.click(f"SessionLabel#{created_mode}", button=2)
            await pilot.pause()
            assert app.current_mode == owner_mode
            assert app.session_tracker.session_count == 1
            assert stopped_agents == 1

            owner_sidebar = app.screen.query_one(CommsSidebar)
            owner_sidebar._refresh()
            await pilot.pause()
            owner_snapshot = owner_sidebar._snapshot()
            assert owner_mode in owner_snapshot.session_threads, (
                owner_snapshot.session_threads,
                app.screen._coordination_root,
                app.screen._agent_session_id,
                app.screen._session_thread,
            )
            local_row = app.screen.query_one(SessionRow)
            local_row.scroll_visible(animate=False)
            await pilot.pause()
            await pilot.click(local_row, button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            menu_items = list(app.screen.query(ContextMenuItem))
            assert [item.action for item in menu_items] == [
                "pin",
                "comms_fork",
                "comms_stop",
                "comms_start",
                "comms_archive",
                "comms_delete",
                "comms_ack",
                "copy",
                "close_view",
            ]
            assert menu_items[0].has_focus
            assert await pilot.hover(menu_items[1])
            await pilot.pause()
            assert menu_items[1].has_focus and not menu_items[0].has_focus
            await pilot.press("down")
            await pilot.pause()
            assert menu_items[2].has_focus and not menu_items[1].has_focus
            assert sum(bool(item.rich_style.reverse) for item in menu_items) == 1
            assert await pilot.hover(menu_items[0])
            await pilot.pause()
            assert menu_items[0].has_focus and not menu_items[1].has_focus
            await pilot.press("escape")
            await pilot.pause()

            conversation = app.screen.conversation
            flash = conversation.query_one(Flash)
            flash.flash("Readable notification", duration=10, style="warning")
            await pilot.pause()
            assert flash.visible
            assert flash.rich_style.color != flash.rich_style.bgcolor
            flash.visible = False
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
            assert me in app.screen.query_one(SessionRow).render().plain

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
            thread_sidebar = app.screen.query_one("#thread-sidebar", SideBar)
            await pilot.click(thread_sidebar.query_one(SideBarToggle))
            await pilot.pause()
            await pilot.click("#plan-panel CollapsibleTitle")
            await pilot.pause()
            assert not plan_panel.collapsed
            await pilot.click("#plan-panel CollapsibleTitle")
            await pilot.pause()
            assert plan_panel.collapsed
            await pilot.click(thread_sidebar.query_one(SideBarToggle))
            await pilot.pause()

            viewer = comms.user_identity(str(project)).name
            comms.send("peer", viewer, "Unread message for human view")
            comms.send("peer", "#all", "Unread channel message for human view")
            pending_before_mark = {
                target: comms.pending_count(me, target)
                for target in ("peer", "other-peer", "#all")
            }
            assert comms.viewer_snapshot(str(project)).unread["peer"] == 1
            assert comms.viewer_snapshot(str(project)).channel_unread["#all"] >= 1
            await pilot.click(row(app.screen, "peer"), button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            assert [item.action for item in app.screen.query(ContextMenuItem)] == [
                "pin",
                "comms_fork",
                "comms_stop",
                "comms_start",
                "comms_archive",
                "comms_delete",
                "comms_ack",
                "copy",
            ]
            await pilot.press("down", "down", "down", "down", "down", "down", "enter")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            assert comms.viewer_snapshot(str(project)).unread.get("peer", 0) == 0
            assert {target: comms.pending_count(me, target)
                    for target in pending_before_mark} == pending_before_mark
            await pilot.click(row(app.screen, "#all"), button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            assert [item.action for item in app.screen.query(ContextMenuItem)] == [
                "pin",
                "comms_ack",
                "copy",
            ]
            await pilot.press("down", "enter")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            assert comms.viewer_snapshot(str(project)).channel_unread["#all"] == 0
            assert {target: comms.pending_count(me, target)
                    for target in pending_before_mark} == pending_before_mark

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
            responses = list(chat.query(IRCMessage))
            assert any("hello from peer" in response.source for response in responses)
            assert not any("private" in response.source for response in responses)
            assert not any("test-model" in response.source for response in responses)
            assert chat.status == ""
            assert not chat.query(AgentThought)
            await app.screen.action_message_style()
            await pilot.pause()
            assert chat.query(AgentResponse)
            await app.screen.action_message_style()
            await pilot.pause()
            assert chat.query(IRCMessage)
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
            # First paint uses a small tail; short records can trigger further
            # bounded pages to fill the viewport before this observation.
            assert INITIAL_HISTORY_PAGE_SIZE <= len(long_chat._history) <= HISTORY_WINDOW_SIZE
            assert [message.body for message, _ in long_chat._history] == [
                f"long history {index:03}"
                for index in range(240 - len(long_chat._history), 240)
            ]
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
                "pin",
                "comms_fork",
                "comms_stop",
                "comms_start",
                "comms_archive",
                "comms_delete",
                "comms_ack",
                "copy",
            ]
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen) and app.screen.kind == "dm"
            dm_mode = app.current_mode
            dm_prompt = app.screen.query_one(Prompt)
            dm_prompt.text = "keep delete"
            dm_prompt.focus()
            await pilot.press("ctrl+w")
            await pilot.pause()
            assert dm_prompt.text == "keep " and app.current_mode == dm_mode
            await pilot.click(f"#close-{dm_mode}")
            await pilot.pause()
            assert app.session_tracker.session_count == 1
            assert isinstance(app.screen, MainScreen)

            owner_mode = app.current_mode
            owner_agent = app.screen._agent
            app.screen._agent = {
                "identity": "agent-comms.openhcs.dev",
                "name": "Agent Comms",
                "short_name": "agent-comms",
                "url": "https://github.com/OpenHCSDev/agent-comms",
                "protocol": "acp",
                "type": "coding",
                "author_name": "OpenHCSDev",
                "author_url": "https://github.com/OpenHCSDev",
                "publisher_name": "OpenHCSDev",
                "publisher_url": "https://github.com/OpenHCSDev",
                "description": "Test agent-comms ACP server",
                "tags": [],
                "help": "",
                "run_command": {"*": f"{sys.executable} -m agent_comms.acp"},
                "actions": {},
            }
            resumable_row = row(app.screen, "resumable-peer")
            assert resumable_row.kind == "thread"
            resumable_row.scroll_visible(animate=False)
            await pilot.pause()
            assert await pilot.click(resumable_row)
            for _ in range(20):
                await pilot.pause()
                if any(
                    "thread transcript complete" in response.source
                    for response in app.screen.query(AgentResponse)
                ):
                    break
            assert isinstance(app.screen, MainScreen)
            assert not isinstance(app.screen, CommsScreen)
            thread_mode = app.current_mode
            assert thread_mode != owner_mode
            assert app.session_tracker.session_count == 2
            assert (
                app.session_tracker.get_session(thread_mode).title == "resumable-peer"
            )
            assert any(
                "thread transcript request" in user_input.content
                for user_input in app.screen.query(UserInput)
            )
            assert any(
                "thread reasoning" in thought.source
                for thought in app.screen.query(AgentThought)
            )
            assert any(
                "thread transcript complete" in response.source
                for response in app.screen.query(AgentResponse)
            )
            assert app.screen.query(ToolCall)
            reused_mode = await app.open_thread_session(
                owner_mode=owner_mode,
                project_path=project,
                target="resumable-peer",
            )
            assert reused_mode == thread_mode
            assert app.session_tracker.session_count == 2
            assert not any(
                session.title.startswith("@resumable-peer")
                for session in app.session_tracker.ordered_sessions
            )
            second_file = root / "second-session.jsonl"
            second_file.write_text(resumable_session.read_text())
            comms.register(
                Thread(
                    name="second-peer",
                    tags=frozenset(),
                    worktree=str(project),
                    session_file=str(second_file),
                )
            )
            app.screen.query_one(CommsSidebar)._refresh()
            await pilot.pause()
            second_row = row(app.screen, "second-peer")
            second_row.scroll_visible(animate=False)
            await pilot.pause()
            assert await pilot.click(second_row)
            for _ in range(300):
                await pilot.pause(0.1)
                if (
                    app.current_mode != thread_mode
                    and app.screen.conversation.agent.session_ready_event.is_set()
                ):
                    break
            second_mode = app.current_mode
            assert second_mode != thread_mode
            assert app.session_tracker.session_count == 3
            first_pid = comms.registry.require("resumable-peer").pid
            second_pid = comms.registry.require("second-peer").pid
            assert first_pid != second_pid
            for target_mode in [thread_mode, second_mode] * 3:
                label = app.screen.query_one(f"SessionLabel#{target_mode}")
                assert await pilot.click(label)
                await pilot.pause()
                assert app.current_mode == target_mode
                assert app.session_tracker.session_count == 3
            assert comms.registry.require("resumable-peer").pid == first_pid
            assert comms.registry.require("second-peer").pid == second_pid
            assert "resumable-peer-2" not in comms.registry
            assert "second-peer-2" not in comms.registry
            hold = gates / "second-peer"
            hold.touch()
            comms.send("resumable-peer", "second-peer", "live round one")
            for _ in range(80):
                await pilot.pause(0.1)
                if any(
                    "reasoning for live round one" in item.source
                    for item in app.screen.query(AgentThought)
                ):
                    break
            assert app.screen.conversation.turn == "agent", (
                [item.source for item in app.screen.query(AgentThought)],
                hold.exists(),
                comms.activity_of("second-peer"),
            )
            assert app.screen.conversation.busy_count == 1
            active_turn = app.screen.conversation._managed_turn_id
            app.screen.conversation.post_message(acp_messages.TurnStarted(active_turn))
            app.screen.conversation.post_message(
                acp_messages.TurnSettled("previous-turn")
            )
            await pilot.pause()
            assert app.screen.conversation._managed_turn_id == active_turn
            assert app.screen.conversation.busy_count == 1
            assert app.screen.query_one(Throbber).busy
            assert app.screen.query_one(Throbber).render() != ""
            assert app.session_tracker.get_session(second_mode).state == "busy"
            assert "⌛" in str(
                app.screen.query_one(f"SessionLabel#{second_mode}").render()
            )
            hold.unlink()
            for _ in range(40):
                await pilot.pause(0.1)
                if (
                    app.screen.conversation._managed_turn_id is None
                    and app.session_tracker.get_session(second_mode).state == "idle"
                ):
                    break
            assert app.screen.conversation.busy_count == 0
            assert app.screen.conversation.turn == "client"
            assert app.session_tracker.get_session(second_mode).state == "idle"
            assert not app.screen.query_one(Throbber).busy
            assert app.screen.query_one(Throbber).render() == ""
            assert (
                len(
                    [
                        item
                        for item in app.screen.query(AgentThought)
                        if "reasoning for live round one" in item.source
                    ]
                )
                == 1
            )
            incoming = [
                item
                for item in app.screen.query(IncomingMessage)
                if item.text == "live round one"
            ]
            assert len(incoming) == 1
            sender_link = incoming[0].query_one(IncomingSender)
            sender_link.scroll_visible(animate=False)
            await pilot.pause()
            assert await pilot.click(sender_link)
            await pilot.pause()
            assert app.current_mode == thread_mode
            assert app.session_tracker.session_count == 3
            comms.send("second-peer", "resumable-peer", "live round two")
            for _ in range(40):
                await pilot.pause(0.1)
                if any(
                    item.text == "live round two"
                    for item in app.screen.query(IncomingMessage)
                ):
                    break
            assert (
                len(
                    [
                        item
                        for item in app.screen.query(IncomingMessage)
                        if item.text == "live round two"
                    ]
                )
                == 1
            )
            for _ in range(40):
                await pilot.pause(0.1)
                if app.screen.conversation._managed_turn_id is None and any(
                    "response for live round two" in item.source
                    for item in app.screen.query(AgentResponse)
                ):
                    break
            first_thoughts = list(app.screen.query(AgentThought))
            hold = gates / "resumable-peer"
            hold.touch()
            app.screen.conversation.post_message(
                messages.UserInputSubmitted("user turn lifecycle")
            )
            for _ in range(40):
                await pilot.pause(0.1)
                if any(
                    "reasoning for user turn lifecycle" in item.source
                    for item in app.screen.query(AgentThought)
                ):
                    break
            assert app.screen.conversation.busy_count == 1
            assert app.screen.conversation.turn == "agent"
            try:
                async with asyncio.timeout(3):
                    while "⌛" not in str(
                        app.screen.query_one(f"SessionLabel#{thread_mode}").render()
                    ):
                        await pilot.pause(.02)
            except TimeoutError:
                raise AssertionError((
                    "Busy thread tab did not observe the activity snapshot within 3 seconds",
                    app.open_tabs, comms.activity_of("resumable-peer"), app.screen._session_thread,
                )) from None
            assert all(
                "user turn lifecycle" not in item.source for item in first_thoughts
            )
            hold.unlink()
            for _ in range(40):
                await pilot.pause(0.1)
                if (
                    app.screen.conversation._managed_turn_id is None
                    and app.session_tracker.get_session(thread_mode).state == "idle"
                ):
                    break
            assert app.screen.conversation.busy_count == 0
            assert app.session_tracker.get_session(thread_mode).state == "idle"
            # Also exercise the saved-session resume entry point. Registry-only
            # attachments do not insert another copy into Toad's saved list.
            first_pk = await DB().session_new(
                "resumable-peer",
                "Agent Comms",
                "agent-comms.openhcs.dev",
                "resumable-peer",
                meta={"cwd": str(project), "agent_data": app.screen._agent},
            )
            assert first_pk is not None
            app.screen.conversation.agent.session_pk = first_pk
            await app.switch_mode(second_mode)
            await app.launch_agent(
                "agent-comms.openhcs.dev",
                agent_session_id="resumable-peer",
                session_pk=first_pk,
                project_path=project,
            ).wait()
            await pilot.pause()
            assert app.current_mode == thread_mode
            assert app.session_tracker.session_count == 3
            assert await pilot.click(f"#close-{second_mode}")
            await pilot.pause()
            assert app.current_mode == thread_mode
            assert app.session_tracker.get_session(second_mode) is None
            assert "second-peer" in comms.registry
            comms.stop("second-peer")
            comms.delete("second-peer")

            external = comms.fork(
                ForkSpec(
                    name="external-peer",
                    parent="resumable-peer",
                    task="external initial turn",
                ),
                pi_bin="/bin/echo",
            )
            try:
                from agent_comms.runtime import socket_path

                for _ in range(40):
                    await pilot.pause(0.1)
                    if socket_path(comms.root, external.pid).exists():
                        break
                external_file = root / "external-session.jsonl"
                external_file.write_text(resumable_session.read_text())
                comms.attach_session(external.name, str(external_file))
                external_mode = await app.open_thread_session(
                    owner_mode=thread_mode, project_path=project, target=external.name
                )
                for _ in range(40):
                    await pilot.pause(0.1)
                    if app.screen.conversation.agent.session_ready_event.is_set():
                        break
                assert external_mode != thread_mode
                assert comms.registry.require(external.name).pid == external.pid
                comms.send("resumable-peer", external.name, "live external attachment")
                for _ in range(40):
                    await pilot.pause(0.1)
                    if any(
                        item.text == "live external attachment"
                        for item in app.screen.query(IncomingMessage)
                    ):
                        break
                assert (
                    len(
                        [
                            item
                            for item in app.screen.query(IncomingMessage)
                            if item.text == "live external attachment"
                        ]
                    )
                    == 1
                )
                app.post_message(messages.SessionDelete(external_mode))
                for _ in range(80):
                    await pilot.pause(0.1)
                    if app.session_tracker.get_session(external_mode) is None:
                        break
                assert app.session_tracker.get_session(external_mode) is None
                assert external.name not in comms.registry
                assert app.current_mode == thread_mode
            finally:
                if external.name in comms.registry:
                    await asyncio.to_thread(comms.stop, external.name)
                    comms.delete(external.name)
                await asyncio.to_thread(os.waitpid, external.pid, 0)
            await app.screen.conversation.rename_session("delete once")
            await pilot.pause()
            deleted_name = app.screen._comms_thread
            assert deleted_name == "delete-once"
            comms.register(
                Thread(
                    name="surviving-child",
                    parent=deleted_name,
                    tags=frozenset(),
                    worktree=str(project),
                    session_file=str(second_file),
                )
            )
            app.screen.query_one(CommsSidebar)._refresh()
            await pilot.pause()
            deleted_pid = comms.registry.require(deleted_name).pid
            deleted_pk = app.screen.conversation.agent.session_pk
            await asyncio.to_thread(comms.stop, deleted_name)
            thread_row = next(
                item
                for item in app.screen.query(SessionRow)
                if item.mode_name == thread_mode
            )
            thread_row.scroll_visible(animate=False)
            await pilot.pause()
            assert await pilot.click(thread_row, button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            delete_item = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == "comms_delete"
            )
            assert await pilot.click(delete_item)
            for _ in range(30):
                await pilot.pause(0.1)
                if app.session_tracker.get_session(thread_mode) is None:
                    break
            assert app.current_mode == owner_mode, (
                app.current_mode,
                [
                    (item.mode_name, item.title)
                    for item in app.session_tracker.ordered_sessions
                ],
                (
                    comms.thread_detail(deleted_name)
                    if deleted_name in comms.registry
                    else "deleted"
                ),
            )
            assert app.session_tracker.session_count == 1
            assert not comms._process_alive(deleted_pid)
            assert deleted_name not in comms.registry
            assert "resumable-peer" not in comms.registry
            assert comms.registry.require("surviving-child").parent is None
            assert comms.registry.require("surviving-child").session_file == str(
                second_file
            )
            assert await DB().session_get(deleted_pk) is None
            await pilot.pause(2)
            assert not {deleted_name, "resumable-peer"} & {
                item.target_name for item in app.screen.query(CommsRow)
            }
            replacement = comms.claim_thread(
                deleted_name, tags=frozenset(), worktree=str(project)
            )
            assert replacement.name == deleted_name
            comms.stop(replacement.name)
            comms.delete(replacement.name)
            comms.stop("surviving-child")
            comms.delete("surviving-child")
            app.screen._agent = owner_agent
            app.screen.query_one(CommsSidebar)._refresh()
            await pilot.pause()

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
            close_view = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == "close_view"
            )
            await pilot.click(close_view)
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
            close_view = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == "close_view"
            )
            await pilot.click(close_view)
            await pilot.pause()
            assert app.session_tracker.session_count == 0
            assert app.current_mode == "store"
            assert await saved_db.session_get(saved_pk) is not None

    print("comms pilot: all interactions passed")


if __name__ == "__main__":
    asyncio.run(main())
