"""Textual-facing: a permission request reaches the modal review screen or the inline question exactly once,
even when Textual's pushed screen is not yet flushed while the request is cancelled or its view is rebound."""

import asyncio

import pytest
from textual.worker import NoActiveWorker, get_current_worker

from support.agents import detached
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


@pytest.mark.parametrize("outcome", ["cancel", "replace"])
async def test_a_request_changed_while_its_screen_push_is_pending_is_cancelled_or_shown_once(workspace, outcome):
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        view = ui.conversation
        agent = detached(workspace.project, "session")
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


async def test_inline_permission_question_is_shown_once_and_answers_only_through_its_current_binding(workspace):
    async with workspace.app() as ui:
        view = ui.conversation
        agent = detached(workspace.project, "session")
        ui.attach_agent(agent)
        await ui.step()
        errors = []
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: errors.append(context))
        task = asyncio.create_task(agent.server.call(permission_call(
            3, "inline-original", kind="read", title="Inline original", option="Allow inline", content=[
                {"type": "content", "content": {"type": "text", "text": "Original inline preview"}}])))
        await ui.until(lambda: view.prompt._ask is not None, why="the inline question")
        request, = agent.permissions.pending
        first_question = view.prompt._ask
        first_binding = agent.controller.surface
        agent.permissions.present()
        await ui.step()
        assert view.prompt._ask is first_question and not view.prompt.ask_queue
        assert request.owns_projection(first_binding, view)
        # Rebinding the same view: the retired binding must not answer or retire the new binding's question.
        agent.detach_surface(view)
        view.bind_agent(agent)
        await ui.until(lambda: view.prompt._ask is not None, why="the question for the new binding")
        assert view.prompt._ask is not first_question
        request.answer(first_binding, request.options[0])
        assert request.pending
        assert request.owns_projection(agent.controller.surface, view)
        assert ui.shows("Inline original") and ui.shows("Allow inline")
        await ui.press("enter")
        result = await task
        assert result["result"]["outcome"] == {"outcome": "selected", "optionId": "allow"}
        await ui.until(lambda: view.prompt._ask is None and not view.prompt.ask_queue, why="the question closed")
        await agent.stop()
        await ui.step()
        assert not errors, errors
