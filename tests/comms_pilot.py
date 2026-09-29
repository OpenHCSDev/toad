from __future__ import annotations
from toad.navigation_target import NavigationContext
from toad.conversation_turn import AgentTurn, ClientTurn

from agent_comms.acp_extension import (
    TurnSettledUpdate,
    TurnStartedUpdate,
    encode_updates,
)

"""Deterministic interaction checks for native comms sessions and menus."""


from toad.navigation_target import DirectTarget

from toad.thread_actions import StartAction, StopAction, ArchiveAction, AcknowledgeAction, ForkAction
import asyncio
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from agent_comms.activity import ActivityState
from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import wire
from agent_comms.thread_status import ArchivedThreadStatus
from agent_comms.threads import Thread
from comms_boundary_fixture import coordination_fact
from runtime_fixture import ToadApp, wait_channel_roster
from textual.content import Content
from textual.style import Style
from textual.widgets import Footer, Markdown
from textual.widgets._footer import FooterKey

from toad import messages, paths
from toad.acp import messages as acp_messages
from toad.acp.agent import Agent as ACPAgent
from toad.db import DB
from toad.pill import pill
from toad.screens.comms import CommsScreen
from toad.screens.main import MainScreen
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.comms_chat import CommsChatView
from toad.mounted_message_history import HISTORY_WINDOW_SIZE, INITIAL_HISTORY_PAGE_SIZE
from toad.widgets.comms_menu import ContextMenu, ContextMenuItem
from toad.widgets.comms_sidebar import (
    CommsRow,
    CommsSidebar,
    CoordinationStatus,
    NewSessionButton,
    ThreadRow,
)
from toad.widgets.conversation import Loading, make_session_title
from toad.widgets.flash import Flash
from toad.widgets.irc_message import IRCMessage
from toad.widgets.project_panel import FilePreview, ProjectSearchButton
from toad.widgets.prompt import Prompt
from toad.widgets.session_tabs import SessionLabel, SessionsTabs
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SideBarToggle
from toad.widgets.throbber import Throbber, ThrobberVisual
from toad.widgets.tool_call import ToolCall


def row(screen, target: str) -> CommsRow:
    return next((item for item in screen.query(CommsRow) if item.target_name == target))


def open_rows(screen):
    return screen.app.workspace_chrome.channels.widget.roster.session_rows


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
        comms = wire(wire_root)
        me = project.name
        comms.registry.declare(
            Thread(name=me, tags=frozenset({"session"}), worktree=str(project))
        )
        comms.registry.declare(
            Thread(name="peer", tags=frozenset({"test"}), worktree=str(project))
        )
        comms.registry.declare(
            Thread(name="other-peer", tags=frozenset(), worktree=str(project))
        )
        resumable_session = root / "resumable-session.jsonl"
        resumable_session.write_text(
            "\n".join(
                (
                    json.dumps(record)
                    for record in [
                        {
                            "type": "message",
                            "message": {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "thread transcript request",
                                    }
                                ],
                            },
                        },
                        {
                            "type": "message",
                            "message": {
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "thinking",
                                        "thinking": "thread reasoning",
                                    },
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
                                "content": [
                                    {"type": "text", "text": "thread tool result"}
                                ],
                                "isError": False,
                            },
                        },
                        {
                            "type": "message",
                            "message": {
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "thread transcript complete",
                                    }
                                ],
                            },
                        },
                    ]
                )
            )
        )
        comms.registry.declare(
            Thread(
                name="resumable-peer",
                tags=frozenset({"test"}),
                worktree=str(project),
                session_file=str(resumable_session),
            )
        )
        comms.messaging.send("peer", "#all", "hello from peer")
        comms.messaging.send("peer", me, "private from peer")
        comms.messaging.send("other-peer", me, "unrelated private message")
        for index in range(HISTORY_WINDOW_SIZE * 2):
            comms.messaging.send("peer", "#test", f"long history {index:03}")
        comms.messaging.acknowledge(me, "#test")
        comms.agents.set_agent_info(
            "peer", model="openrouter/test-model", context_used=250, context_size=1000
        )
        comms.agents.set_activity(
            "peer", ActivityState.THINKING, "reviewing the change"
        )
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
                (
                    key.get_component_rich_style("footer-key--key").reverse
                    for key in footer_keys
                )
            )
            assert any((action.endswith("toggle_irc") for action in footer_actions))
            assert not any((action.endswith("go_home") for action in footer_actions))
            assert not any((action.endswith("settings") for action in footer_actions))
            irc_key = next(
                (key for key in footer_keys if key.action.endswith("toggle_irc"))
            )
            session_label = app.screen.query_one(SessionLabel)
            assert await pilot.hover(session_label)
            assert session_label.rich_style.reverse
            info_bar = app.screen.query_one("#info-container")
            footer = app.screen.query_one(Footer)
            assert info_bar.region.bottom == footer.region.y
            throbber = app.selected_session.conversation.query_one(Throbber)
            throbber.add_class("-busy")
            await pilot.pause()
            assert throbber.region.bottom == app.selected_session.conversation.prompt.region.y, (
                throbber.region,
                app.selected_session.conversation.prompt.region,
            )
            throbber.remove_class("-busy")
            await pilot.click(irc_key)
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen)
            assert await pilot.click(f"#close-{app.selected_mode}")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            assert app.session_tracker.session_count == 1
            session_rows = open_rows(app.screen)
            assert len(session_rows) == 1
            assert session_rows[0].current
            assert await pilot.hover(session_rows[0])
            assert (
                session_rows[0].rich_style.color != session_rows[0].rich_style.bgcolor
            ), (session_rows[0].rich_style, session_rows[0].classes, app.focused,
                app.sidebar_state, app.screen.query_one(CommsSidebar).navigation_ready.is_set())
            assert not app.screen.query_one("#thread-sidebar", SideBar)._panels_loaded
            shell_sidebar = app.screen.query_one("#channels-sidebar", SideBar)
            panels = list(shell_sidebar.query(SideBarCollapsible))
            assert (
                panels[0].query_one("CollapsibleTitle").region.y == panels[0].region.y
            )
            conversation = app.selected_session.conversation
            assert conversation.prompt.region.x == conversation.region.x
            assert conversation.contents.region.x == conversation.region.x + 1
            assert all(
                (panel.region.height <= 2 for panel in panels if panel.collapsed)
            ), [(panel.title, panel.collapsed, panel.region.height) for panel in panels]
            controls = shell_sidebar.query_one("#sidebar-controls")
            viewport = shell_sidebar.query_one("#sidebar-panels")
            assert controls.region.y - viewport.region.bottom <= 1
            assert controls.region.bottom == shell_sidebar.region.bottom
            await pilot.click(panels[0].query_one("CollapsibleTitle"))
            await pilot.pause()
            assert panels[0].region.height <= 2
            await pilot.click(panels[0].query_one("CollapsibleTitle"))
            thread_sidebar = app.screen.query_one("#thread-sidebar", SideBar)
            await pilot.click(thread_sidebar.query_one(SideBarToggle))
            await thread_sidebar.wait_content_ready()
            await pilot.pause()
            coordination = app.screen.query_one(CoordinationStatus)
            assert "persistent" in coordination.render().plain
            assert str(wire_root) in str(coordination.tooltip)
            assert thread_sidebar.region.x >= conversation.region.right
            thread_panels = list(thread_sidebar.query(SideBarCollapsible))
            assert [panel.title for panel in thread_panels] == [
                "Thread",
                "Comms",
                "Plan",
                "Project",
                "Recovery",
            ]
            assert not thread_panels[-1].display, (
                "Optional recovery view must remain default-off"
            )
            project_panel = thread_panels[-2]
            await pilot.click(project_panel.query_one("CollapsibleTitle"))
            await pilot.pause()
            assert project_panel.region.height > 2
            await pilot.click(project_panel.query_one("CollapsibleTitle"))
            await pilot.pause()
            assert project_panel.region.height <= 2
            await pilot.click(thread_sidebar.query_one(SideBarToggle))
            await pilot.pause()
            assert thread_sidebar.collapsed and (not shell_sidebar.collapsed)
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
            assert (
                app.screen.query_one(SessionsTabs).region.x
                == app.screen.query_one("TabHistoryControls").region.right
            )
            assert shell_sidebar.render() == ">"
            assert sidebar_toggle.tooltip == "Expand sidebar"
            await pilot.hover(app.selected_session.conversation.prompt)
            collapsed_background = sidebar_toggle.styles.background
            assert await pilot.hover(sidebar_toggle)
            await pilot.pause()
            assert sidebar_toggle.styles.background != collapsed_background
            await pilot.click(sidebar_toggle)
            await pilot.pause()
            assert not shell_sidebar.collapsed
            expected_width = (
                app.size.width
                * app.sidebar_layout.get("channels-sidebar").width_percent
                // 100
            )
            assert shell_sidebar.region.width == expected_width
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
            focused_session = open_rows(app.screen)[0]
            assert focused_session.has_focus
            shortcut_snapshot = app.screen.query_one(CommsSidebar)._snapshot()
            assert focused_session.has_class("-wire-thread"), (
                shortcut_snapshot.session_threads,
                shortcut_snapshot.all_people,
                app.screen._session_thread,
            )
            preview_owner_mode = app.selected_mode
            await app.screen.open_file_preview(preview_path)
            await pilot.pause()
            from toad.screens.file_preview import FilePreviewScreen

            assert isinstance(app.screen, FilePreviewScreen)
            preview_mode = app.selected_mode
            assert any((tab.mode_name == preview_mode for tab in app.open_tabs))
            assert app.screen.query_one(FilePreview).query_one(Markdown)
            await app.session_navigation.close(preview_mode)
            assert app.selected_mode == preview_owner_mode
            search_button = app.screen.query_one(ProjectSearchButton)
            search_button.action_search()
            await pilot.pause()
            assert app.selected_session.conversation.prompt.path_search.is_open
            app.selected_session.conversation.prompt.path_search.is_open = False
            owner_mode = app.selected_mode
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
            created_mode = app.selected_mode
            assert created_mode != owner_mode
            assert app.session_tracker.session_count == 2
            session_rows = open_rows(app.screen)
            assert len(session_rows) == 1
            assert app.screen.query_one(f"SessionLabel#{created_mode}")
            created_conversation = app.selected_session.conversation
            assert app.session_tracker.get_session(created_mode).title == "New Session"
            managed_thread = "managed-test-thread"
            comms.registry.declare(
                Thread(
                    name=managed_thread,
                    tags=frozenset({"acp"}),
                    worktree=str(project),
                    process_identity=ProcessIdentity.capture(os.getpid()),
                )
            )
            startup_agent = ACPAgent(
                project,
                {
                    "name": "Startup fixture",
                    "identity": "fixture",
                    "run_command": {"*": "true"},
                },
                managed_thread,
            )
            startup_agent.attach_surface(created_conversation)
            startup_agent._pending_session_name = None
            startup_agent.process.process = SimpleNamespace(pid=os.getpid())
            startup_agent.session_pk = None
            startup_agent.comms_consumer_class(
                startup_agent, startup_agent.session_id
            ).dispatch_sync(coordination_fact(managed_thread, str(wire_root)))
            await pilot.pause()
            assert app.session_tracker.get_session(created_mode).title == managed_thread
            await startup_agent.set_session_name("Name this from my first prompt")
            created_conversation.post_message(
                messages.SessionUpdate(name="Name this from my first prompt")
            )
            await pilot.pause()
            renamed_thread = "Name-this-from-my-first-prompt"
            assert comms.registry.require(managed_thread).name == renamed_thread
            assert app.screen._session_thread == renamed_thread
            local_sidebar = app.screen.query_one("#thread-sidebar", SideBar)
            local_sidebar.reveal()
            await local_sidebar.wait_content_ready()
            assert (
                renamed_thread
                in app.screen.query_one(CoordinationStatus).render().plain
            )
            local_sidebar.toggle(focus=False)
            assert not any(item.target_name == managed_thread for item in app.screen.query(ThreadRow))
            assert [item.mode_name for item in app.screen.query(ThreadRow)
                    if item.target_name == renamed_thread] == [created_mode]
            assert (
                app.session_tracker.get_session(created_mode).title
                == "Name this from my first prompt"
            )
            startup_agent.updates.accept(
                sessionId=managed_thread,
                update={
                    "sessionUpdate": "session_info_update",
                    "title": "Name this from my first prompt",
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
            created_sidebar = app.screen.query_one("#channels-sidebar", SideBar)
            created_sidebar.toggle()
            await pilot.pause()
            assert created_sidebar.collapsed
            assert app.settings.sidebar.hide
            await app.switch_mode(owner_mode)
            await pilot.pause()
            assert app.screen.query_one("#channels-sidebar", SideBar).collapsed
            assert [
                item.mode_name
                for item in app.screen.query(ThreadRow)
                if item.target_name == renamed_thread
            ] == [created_mode]
            assert len(open_rows(app.screen)) == 2
            await app.switch_mode(created_mode)
            await pilot.pause()
            assert app.screen.query_one("#channels-sidebar", SideBar).collapsed
            app.screen.query_one("#channels-sidebar", SideBar).reveal()
            await pilot.pause()
            assert not app.settings.sidebar.hide
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
            assert app.selected_mode == owner_mode
            assert app.session_tracker.session_count == 1
            assert stopped_agents == 1
            owner_sidebar = app.screen.query_one(CommsSidebar)
            owner_sidebar._refresh()
            await pilot.pause()
            owner_snapshot = owner_sidebar._snapshot()
            assert owner_mode in owner_snapshot.session_threads, (
                owner_snapshot.session_threads,
                app.screen.initial_coordination_root,
                app.screen._agent_session_id,
                app.screen._session_thread,
            )
            local_row = open_rows(app.screen)[0]
            local_row.scroll_visible(animate=False)
            await pilot.pause()
            await pilot.click(local_row, button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            menu_items = list(app.screen.query(ContextMenuItem))
            assert [item.action for item in menu_items] == [
                "pin",
                ForkAction.declared_name,
                StopAction.declared_name,
                StartAction.declared_name,
                ArchiveAction.declared_name,
                AcknowledgeAction.declared_name,
                "copy",
                "close_view",
            ]
            assert menu_items[0].has_focus
            assert await pilot.hover(menu_items[1])
            await pilot.pause()
            assert menu_items[1].has_focus and (not menu_items[0].has_focus)
            await pilot.press("down")
            await pilot.pause()
            assert menu_items[2].has_focus and (not menu_items[1].has_focus)
            assert sum((bool(item.rich_style.reverse) for item in menu_items)) == 1
            assert await pilot.hover(menu_items[0])
            await pilot.pause()
            assert menu_items[0].has_focus and (not menu_items[1].has_focus)
            await pilot.press("escape")
            await pilot.pause()
            conversation = app.selected_session.conversation
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
            assert me in open_rows(app.screen)[0].render().plain
            opened = await DirectTarget("missing-peer").open(NavigationContext(app, owner_mode, project, me))
            await pilot.pause()
            assert opened == owner_mode
            assert app.session_tracker.session_count == 1
            conversation._loading = await conversation.post(Loading("Thinking…"))
            current_summary = app.session_tracker.get_session(owner_mode).summary
            conversation.turns.owner = ClientTurn()
            conversation.post_message(acp_messages.Update("text", "Background message"))
            await pilot.pause()
            assert (
                app.session_tracker.get_session(owner_mode).summary == current_summary
            )
            conversation.turns.owner = AgentTurn()
            conversation.post_message(acp_messages.Update("text", "Finished answer"))
            await pilot.pause()
            assert (
                app.session_tracker.get_session(owner_mode).summary
                == "Writing response"
            )
            protocol_agent = ACPAgent(
                project,
                {
                    "name": "Protocol fixture",
                    "identity": "fixture",
                    "run_command": {"*": "true"},
                },
                "pilot-session",
            )
            protocol_agent.attach_surface(conversation)
            previous_agent = conversation.agent
            conversation.set_reactive(type(conversation).agent, protocol_agent)
            protocol_agent.updates.accept(
                "pilot-session",
                {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": ""},
                    "_meta": encode_updates(
                        TurnStartedUpdate("pilot-turn", None, None, None)
                    ),
                },
            )
            protocol_agent.updates.accept(
                "pilot-session",
                {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": ""},
                    "_meta": encode_updates(TurnSettledUpdate("pilot-turn")),
                },
            )
            await pilot.pause()
            settled = app.session_tracker.get_session(owner_mode)
            assert settled.state == "idle"
            assert settled.summary == "Ready for review"
            conversation.set_reactive(type(conversation).agent, previous_agent)
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
            conversation.turns.owner = AgentTurn()
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
            assert conversation.turns.owner.busy
            cancel_agent.release.set()
            await pilot.pause()
            if conversation._loading is not None:
                await conversation._loading.remove()
            conversation._loading = None
            conversation.agent = original_agent
            conversation.turns.owner = ClientTurn()
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
            viewer = comms.messaging.user_identity(str(project)).name
            comms.messaging.send("peer", viewer, "Unread message for human view")
            comms.messaging.send(
                "peer", "#all", "Unread channel message for human view"
            )
            pending_before_mark = {
                target: comms.bus.pending_count(me, target)
                for target in ("peer", "other-peer", "#all")
            }
            assert comms.views.viewer_snapshot(str(project)).unread["peer"] == 1
            assert comms.views.viewer_snapshot(str(project)).channel_unread["#all"] >= 1
            await pilot.click(row(app.screen, "peer"), button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            assert [item.action for item in app.screen.query(ContextMenuItem)] == [
                "pin",
                ForkAction.declared_name,
                StopAction.declared_name,
                StartAction.declared_name,
                ArchiveAction.declared_name,
                AcknowledgeAction.declared_name,
                "copy",
            ]
            ack_item = next(item for item in app.screen.query(ContextMenuItem)
                            if item.action == AcknowledgeAction.declared_name)
            await pilot.click(ack_item)
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            assert comms.views.viewer_snapshot(str(project)).unread.get("peer", 0) == 0
            assert {
                target: comms.bus.pending_count(me, target)
                for target in pending_before_mark
            } == pending_before_mark
            await pilot.click(row(app.screen, "#all"), button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            assert [item.action for item in app.screen.query(ContextMenuItem)] == [
                "pin",
                AcknowledgeAction.declared_name,
                "copy",
            ]
            await pilot.press("down", "enter")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            assert comms.views.viewer_snapshot(str(project)).channel_unread["#all"] == 0
            assert {
                target: comms.bus.pending_count(me, target)
                for target in pending_before_mark
            } == pending_before_mark
            await pilot.click(row(app.screen, "other-peer"), button=3)
            await pilot.pause()
            stop_item = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == StopAction.declared_name
            )
            await pilot.click(stop_item)
            await pilot.pause()
            assert comms.views.thread_detail("other-peer")["status"] == "stopped"
            await pilot.click(row(app.screen, "other-peer"), button=3)
            await pilot.pause()
            archive_item = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == ArchiveAction.declared_name
            )
            await pilot.click(archive_item)
            await pilot.pause()
            assert comms.registry.status("other-peer") == ArchivedThreadStatus()
            assert not any(
                (
                    item.target_name == "other-peer"
                    for item in app.screen.query(CommsRow)
                )
            )
            retained_owner_rows = tuple(open_rows(app.screen))
            await pilot.click(row(app.screen, "#all"))
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen)
            assert app.screen.target == "#all"
            assert row(app.screen, "#all").selected
            assert app.session_tracker.session_count == 1
            assert len(open_rows(app.screen)) == 1
            owner_screen = app.get_screen_stack(owner_mode)[-1]
            assert tuple(open_rows(owner_screen)) == retained_owner_rows, (
                "Tab switch rebuilt the warm roster"
            )
            assert all((item.is_attached for item in retained_owner_rows))
            first_channel_mode = app.selected_mode
            chat = app.screen.query_one(CommsChatView)
            assert chat.prompt.prompt_text_area.has_focus
            responses = list(chat.query(IRCMessage))
            assert any(("hello from peer" in response.source for response in responses))
            assert not any(("private" in response.source for response in responses))
            assert not any(("test-model" in response.source for response in responses))
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
                message.body for message in comms.views.channel_history("#all")
            ]
            owner_row = next(
                (item for item in open_rows(app.screen) if item.mode_name == owner_mode)
            )
            await pilot.click(owner_row)
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            assert len(open_rows(app.screen)) == 1, (
                "Resumed roster did not restore its model projection"
            )
            await pilot.click(row(app.screen, "#all"))
            await pilot.pause()
            async with asyncio.timeout(10):
                while app.selected_mode != first_channel_mode:
                    await pilot.pause(0.01)
            assert app.selected_mode == first_channel_mode
            assert app.session_tracker.session_count == 1
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            await pilot.click(row(app.screen, "#test"))
            await pilot.pause()
            long_chat = app.screen.query_one(CommsChatView)
            assert (
                INITIAL_HISTORY_PAGE_SIZE
                <= len(long_chat.message_history.rows)
                <= HISTORY_WINDOW_SIZE
            )
            assert [message.body for message, _ in long_chat.message_history.rows] == [
                f"long history {index:03}"
                for index in range(240 - len(long_chat.message_history.rows), 240)
            ]
            assert "long history 239" in long_chat.message_history.rows[-1][1].source
            previous_oldest = long_chat.message_history.rows[0][0].seq
            long_chat.message_history.edge_scheduled = True
            long_chat.window.scroll_home(animate=False)
            await pilot.pause()
            anchor = long_chat.message_history.rows[0][1]
            anchor_y = anchor.region.y
            long_chat.message_history.edge_scheduled = False
            long_chat.message_history.on_scroll(long_chat.window.scroll_y)
            for _ in range(10):
                if long_chat.message_history.rows[0][0].seq < previous_oldest:
                    break
                await pilot.pause()
            assert long_chat.message_history.rows[0][0].seq < previous_oldest
            await pilot.pause()
            assert abs(anchor.region.y - anchor_y) <= 1
            while not long_chat.message_history.has_newer:
                page = long_chat.message_history.read_page(
                    comms, before=long_chat.message_history.rows[0][0].seq
                )
                await long_chat.message_history.mount_page(page, older=True)
            sequences = [message.seq for message, _ in long_chat.message_history.rows]
            assert len(sequences) == HISTORY_WINDOW_SIZE
            assert len(sequences) == len(set(sequences))
            assert sequences[0] < previous_oldest
            assert long_chat.message_history.has_newer
            newest_before = sequences[-1]
            page = long_chat.message_history.read_page(comms, after=newest_before)
            await long_chat.message_history.mount_page(page, older=False)
            assert long_chat.message_history.rows[-1][0].seq > newest_before
            assert len(long_chat.message_history.rows) == HISTORY_WINDOW_SIZE
            assert long_chat.message_history.has_older
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            await pilot.click(row(app.screen, "peer"))
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen)
            assert app.screen.kind == "dm"
            assert row(app.screen, "peer").selected
            tabs = app.screen.query_one(SessionsTabs)
            assert tabs.current_session == app.selected_mode
            active_tab = tabs.query_one(f"#{app.selected_mode}", SessionLabel)
            assert active_tab.has_class("-current")
            assert active_tab.render().plain == "@peer"
            assert app.session_tracker.session_count == 1
            assert len(open_rows(app.screen)) == 1
            assert not any(
                (
                    session.title == "@peer"
                    for session in app.session_tracker.ordered_sessions
                )
            )
            await pilot.click(row(app.screen, "peer"), button=3)
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)
            assert [item.action for item in app.screen.query(ContextMenuItem)] == [
                "pin",
                ForkAction.declared_name,
                StopAction.declared_name,
                StartAction.declared_name,
                ArchiveAction.declared_name,
                AcknowledgeAction.declared_name,
                "copy",
            ]
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, CommsScreen) and app.screen.kind == "dm"
            dm_mode = app.selected_mode
            dm_prompt = app.screen.query_one(Prompt)
            dm_prompt.text = "keep delete"
            dm_prompt.focus()
            await pilot.press("ctrl+w")
            await pilot.pause()
            assert dm_prompt.text == "keep " and app.selected_mode == dm_mode
            await pilot.click(f"#close-{dm_mode}")
            await pilot.pause()
            assert app.session_tracker.session_count == 1
            assert isinstance(app.screen, MainScreen)
            async with asyncio.timeout(10):
                await wait_channel_roster(app, pilot, "#all")
                await pilot.pause()
                while True:
                    channel_row = next(
                        (
                            item
                            for item in app.screen.query(CommsRow)
                            if item.target_name == "#all" and item.is_attached
                        ),
                        None,
                    )
                    if channel_row is not None:
                        channel_row.scroll_visible(animate=False)
                        await pilot.pause(0.01)
                        placement = app.screen._compositor.visible_widgets.get(
                            channel_row
                        )
                        if placement is not None:
                            region, clip = placement
                            visible = region.intersection(clip).intersection(
                                app.screen.size.region
                            )
                            if visible:
                                x = visible.x + visible.width // 2
                                y = visible.y + visible.height // 2
                                if app.screen.get_widget_at(x, y)[0] is channel_row:
                                    click_offset = (x - region.x, y - region.y)
                                    break
                    else:
                        await pilot.pause(0.01)
                assert await pilot.click(channel_row, offset=click_offset), (
                    "Channel revisit click missed its native row",
                    channel_row.region,
                    app.screen.query_one("#channels-sidebar", SideBar).collapsed,
                    click_offset,
                    app.selected_mode,
                    app.screen.get_widget_at(x, y)[0],
                )
                await pilot.pause()
                while app.selected_mode != first_channel_mode:
                    await pilot.pause(0.01)
            assert app.selected_mode == first_channel_mode
            await pilot.press("escape")
            await pilot.pause()
            owner_mode = app.selected_mode
            owner_row = next(
                (item for item in open_rows(app.screen) if item.mode_name == owner_mode)
            )
            await pilot.click(owner_row, button=3)
            await pilot.pause()
            close_view = next(
                (
                    item
                    for item in app.screen.query(ContextMenuItem)
                    if item.action == "close_view"
                )
            )
            await pilot.click(close_view)
            await pilot.pause()
            assert app.session_tracker.session_count == 0
            assert app.selected_mode == "store"
            state_path = root / "state"
            state_path.mkdir()
            paths.get_state = lambda: state_path
            await app.session_navigation.new(app.get_main_screen)
            await pilot.pause()
            saved_mode = app.selected_mode
            saved_db = DB()
            assert await saved_db.create()
            saved_pk = await saved_db.session_new(
                "Retain saved history", "Pilot agent", "pilot-agent", "pilot-session"
            )
            assert saved_pk is not None
            app.screen._session_pk = saved_pk
            saved_row = next(
                (item for item in open_rows(app.screen) if item.mode_name == saved_mode)
            )
            await pilot.click(saved_row, button=3)
            await pilot.pause()
            close_view = next(
                (
                    item
                    for item in app.screen.query(ContextMenuItem)
                    if item.action == "close_view"
                )
            )
            await pilot.click(close_view)
            await pilot.pause()
            assert app.session_tracker.session_count == 0
            assert app.selected_mode == "store"
            assert await saved_db.session_get(saved_pk) is not None
    print("comms pilot: all interactions passed")


if __name__ == "__main__":
    asyncio.run(main())
