"""Textual-facing: a permission request reaches the modal review screen or the inline question exactly once,
even when Textual's pushed screen is not yet flushed while the request is cancelled or its view is rebound."""

import asyncio

import pytest
from textual.worker import NoActiveWorker, get_current_worker

from toad.screens.permissions import PermissionsScreen


def permission_call(request_id, tool_call_id, *, kind, title, content, option):
    return {"jsonrpc": "2.0", "id": request_id, "method": "session/request_permission", "params": {
        "sessionId": "session", "options": [{"optionId": "allow", "name": option, "kind": "allow_once"}],
        "toolCall": {"toolCallId": tool_call_id, "kind": kind, "title": title, "content": content}}}


def diff_call(workspace, name):
    return permission_call(1, "race-" + name, kind="edit", title="Pending review", option="Allow", content=[
        {"type": "diff", "path": str(workspace.project / "test.txt"),
         "oldText": "old visible value", "newText": "new visible value"}])


class HeldPush:
    """Holds Textual's callback flush for the permission worker until released."""

    def __init__(self, app, view):
        self.entered, self.release, self.actual = asyncio.Event(), asyncio.Event(), app._flush_next_callbacks
        self.view = view
        app._flush_next_callbacks = self.flush

    async def flush(self):
        try:
            worker = get_current_worker()
        except NoActiveWorker:
            worker = None
        if worker is not None and worker.name == "request_permissions" and worker.node is self.view:
            self.entered.set()
            await self.release.wait()
        await self.actual()


@pytest.mark.parametrize("outcome", ["cancel"])
async def test_a_request_changed_while_its_screen_push_is_pending_is_cancelled_or_shown_once(workspace, outcome):
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        view = ui.conversation
        agent = ui.detached_agent("session")
        view.agent = agent  # binds the view once, as opening a session does
        await ui.step()
        errors = []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda loop, context: errors.append(context))
        held = HeldPush(app, view)
        task = asyncio.create_task(agent.server.call(diff_call(workspace, outcome)))
        await held.entered.wait()
        request, = agent.permissions.pending
        workers = [w for w in view.workers if w.node is view and w.name == "request_permissions"]
        assert not isinstance(app.screen, PermissionsScreen)
        if outcome == "cancel":
            completed = asyncio.Event()
            request.future.add_done_callback(lambda future: completed.set())
            request.cancel()
            await completed.wait()
        else:
            agent.detach_surface(view)
            view.bind_agent(agent)
            await ui.step()
            assert request.pending and agent.controller.surface.owns(view)
        held.release.set()
        for worker in workers:
            await worker.wait()
        await ui.step()
        if outcome == "cancel":
            result = await task
            assert result["result"]["outcome"] == {"outcome": "cancelled"}
            assert not isinstance(app.screen, PermissionsScreen)
        else:
            await ui.until(lambda: isinstance(app.screen, PermissionsScreen), why="the review screen")
            assert ui.shows("visible value") and ui.shows("Allow")
            await ui.press("enter")
            result = await task
            assert result["result"]["outcome"] == {"outcome": "selected", "optionId": "allow"}
            await ui.until(lambda: not isinstance(app.screen, PermissionsScreen), why="the review screen closed")
        assert ui.failure() is None
        await agent.stop()
        assert not errors, errors
