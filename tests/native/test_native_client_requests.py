"""Requests the agent makes of its client (files, permission, terminal) on a real native session,
and what happens to them when the tab is left, the session is replaced or the agent is stopped."""

import asyncio

from support.native import native_session
from toad.db import DB
from toad.navigation_context import NavigationContext
from toad.navigation_target import channel_target
from toad.screens.permissions import PermissionReview
from toad.widgets.terminal_tool import TerminalTool

ALLOW = {"optionId": "allow", "name": "Allow once", "kind": "allow_once"}
REJECT = {"optionId": "reject", "name": "Reject", "kind": "reject_once"}


async def test_client_requests_follow_the_session_they_belong_to(workspace, native_package):
    async with native_session(workspace, native_package) as native:
        ui, agent, comms, provider = native.ui, native.agent, native.comms, native.provider
        app, _pilot = ui.textual
        view = ui.conversation
        owner_tab = ui.selected_tab
        project = agent.project_root_path
        await ui.until_agent_ready()
        await ui.write_draft("CLIENT_SESSION_SAVED_HISTORY")
        await ui.press("enter")
        await ui.until(lambda: "NATIVE_RESPONSE_1" in ui.painted(view.window), seconds=30, why="the answer")
        await ui.until(lambda: not native.executing, seconds=20, why="the turn to finish")
        await agent.session.reconnect()
        assert agent.session.ready
        await ui.until(lambda: "NATIVE_RESPONSE_1" in ui.painted(view.window), seconds=20, why="history after reattaching")

        calls = iter(range(101, 200))

        async def request(method, **params):
            result = await agent.server.call({"jsonrpc": "2.0", "id": next(calls), "method": method,
                                              "params": {"sessionId": agent.session_id, **params}})
            assert "error" not in result, result
            return result["result"]

        def reviewing():
            return isinstance(app.screen, PermissionReview)

        await request("fs/write_text_file", path="client.txt", content="old client value\nretained line")
        assert (await request("fs/read_text_file", path="client.txt", line=2, limit=1))["content"] == "retained line"
        tool = {"toolCallId": "client-edit", "title": "CLIENT_BOUND_PERMISSION", "kind": "edit",
                "content": [{"type": "diff", "path": str(project / "client.txt"),
                             "oldText": "old client value", "newText": "CLIENT_NEW_VALUE"}]}
        agent.updates.accept(agent.session_id, {"sessionUpdate": "tool_call", **tool, "status": "in_progress"})
        permission = asyncio.create_task(request(
            "session/request_permission", options=[ALLOW, REJECT], toolCall={"toolCallId": "client-edit"}))
        await ui.until(reviewing, why="the permission review")
        await ui.until(lambda: ui.shows("CLIENT_NEW_VALUE") and ui.shows("Allow"), why="the proposed edit and its choices")
        await ui.press("a")
        assert (await permission)["outcome"] == {"outcome": "selected", "optionId": "allow"}
        await request("fs/write_text_file", path="client.txt", content="CLIENT_NEW_VALUE\nretained line")
        assert (project / "client.txt").read_text().startswith("CLIENT_NEW_VALUE")

        terminal_id = (await request("terminal/create", command="sh",
                                     args=["-c", "printf 'CLIENT_TERMINAL_RETAINED\\n'"]))["terminalId"]
        assert (await request("terminal/wait_for_exit", terminalId=terminal_id))["exitCode"] == 0
        assert "CLIENT_TERMINAL_RETAINED" in (await request("terminal/output", terminalId=terminal_id))["output"]
        await ui.until_shows("CLIENT_TERMINAL_RETAINED")
        execution = agent.controller.terminals.require(terminal_id)

        # Leaving the tab and returning keeps the terminal, the draft and the editor.
        await ui.write_draft("CLIENT_SESSION_UNSENT_DRAFT")
        document = view.prompt.prompt_text_area.document
        undo = view.prompt.prompt_text_area.history
        user = comms.messaging.user_identity(str(project)).name
        await channel_target("#team").open(NavigationContext(app, owner_tab, project, user))
        await ui.select_tab(owner_tab)
        returned = ui.conversation
        assert returned.agent is agent and agent.controller.terminals.require(terminal_id) is execution
        await ui.until(lambda: returned.query_one_optional(f"#{terminal_id}", TerminalTool) is not None,
                       why="the terminal block after returning")
        await ui.until_shows("CLIENT_TERMINAL_RETAINED")
        assert ui.draft() == "CLIENT_SESSION_UNSENT_DRAFT"
        assert returned.prompt.prompt_text_area.document is document
        assert returned.prompt.prompt_text_area.history is undo
        await request("terminal/release", terminalId=terminal_id)

        # A pending permission survives the view being detached and is shown again when it returns.
        pending = asyncio.create_task(request(
            "session/request_permission", options=[ALLOW, REJECT],
            toolCall={**tool, "toolCallId": "retained-permission"}))
        await ui.until(reviewing, why="the second permission review")
        owned, = agent.permissions.pending
        agent.detach_surface(returned)
        await ui.until(lambda: not reviewing(), why="the review to close with its view")
        assert owned.pending and not agent.controller.surface.owns(returned)
        returned.bind_agent(agent)
        await ui.until(reviewing, why="the review to return with its view")
        await ui.until_shows("CLIENT_NEW_VALUE")
        assert agent.permissions.pending == (owned,)
        await ui.press("r")
        assert (await pending)["outcome"] == {"outcome": "selected", "optionId": "reject"}

        # Replacing the session cancels its pending permission.
        replaced = asyncio.create_task(request(
            "session/request_permission", options=[ALLOW], toolCall={**tool, "toolCallId": "replaced-permission"}))
        await ui.until(reviewing, why="the third permission review")
        first_session = agent.session_id
        await agent.session.new()
        assert agent.session_id != first_session
        saved = agent.session.pk
        assert saved is not None and agent.session.ready
        await agent.set_session_name(agent.session_id)
        assert (await DB().session_get(saved)).title == agent.session_id
        assert (await replaced)["outcome"] == {"outcome": "cancelled"}

        # Stopping the agent cancels its pending permission and releases its terminals.
        stopped = asyncio.create_task(request(
            "session/request_permission", options=[ALLOW], toolCall={**tool, "toolCallId": "stopped-permission"}))
        await ui.until(reviewing, why="the fourth permission review")
        await agent.stop()
        assert (await stopped)["outcome"] == {"outcome": "cancelled"}
        assert not agent.permissions.pending and not agent.controller.terminals.executions
        assert len(provider.requests) == 1
