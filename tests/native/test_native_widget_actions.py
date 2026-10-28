"""Keys and clicks on questions and the permission dialog during a real native session,
and a double Escape that cancels a running native turn."""

import asyncio
from pathlib import Path

from acp import schema

from support.native import ControlledProvider, native_session
from toad.answer import Answer
from toad.question_actions import QuestionAction, AllowOnceAction
from textual.document._editing import EditingMode
from toad.screens.permissions import PermissionsScreen
from toad.widgets.flash import Flash
from toad.widgets.question import Option, Question


async def answered_once_and_reattached(native):
    ui, agent, comms = native.ui, native.agent, native.comms
    view = ui.conversation
    await ui.until_agent_ready()
    await ui.write_draft("ACTION_NATIVE_SAVED_HISTORY")
    await ui.press("enter")
    await ui.until(lambda: "NATIVE_RESPONSE_1" in ui.painted(view.window), seconds=30, why="the answer")
    await ui.until(lambda: not native.executing, seconds=20, why="the turn to finish")
    assert len(native.provider.requests) == 1
    owner = comms.registry.require("beta").process_identity
    await agent.session.reconnect()
    await ui.until(agent.session.settled.is_set, seconds=30, why="the reconnect to settle")
    await ui.until(lambda: ui.agent_ready() and "NATIVE_RESPONSE_1" in ui.painted(view.window), seconds=20,
                   why="history after reattaching")
    assert len(native.provider.requests) == 1 and comms.registry.require("beta").process_identity == owner


async def test_question_and_permission_actions_leave_the_draft_alone(workspace, native_package):
    async with native_session(workspace) as native:
        ui, agent = native.ui, native.agent
        app, pilot = ui.textual
        view = ui.conversation
        await answered_once_and_reattached(native)
        await ui.write_draft("KEEP_ACTION_DRAFT")
        document = view.prompt.prompt_text_area.document
        undo = view.prompt.prompt_text_area.history
        assert view.check_action("cancel", ()) is None
        assert view.check_action("focus_terminal", ()) is None
        assert view.check_action("mode_switcher", ()) is False
        await ui.press("escape")
        assert not native.executing

        app.set_keymap({AllowOnceAction.binding_id(EditingMode): "f9"})
        selected = []
        view.ask([Answer("Allow native choice", "first-allow", kind="allow_once"),
                  Answer("Reject native choice", "first-reject", kind="reject_once")],
                 "DECLARED_QUESTION", callback=selected.append)
        question = view.prompt.query_one(Question)
        await ui.until(lambda: len(question.query(Option)) == 2 and ui.shows("DECLARED_QUESTION"), why="the question")
        question.focus()
        assert question.query(Option)[0].keys == ("f9",)
        await ui.press("a")
        assert not selected
        await ui.press("down")
        assert question.selection == 1
        assert await pilot.click(question.query(Option)[0].query_one("#label"), offset=(1, 0))
        assert question.selection == 0
        assert question.check_action("allow_always", ()) is False
        await ui.press("A")
        assert not selected
        await ui.press("enter", "enter")
        assert [answer.id for answer in selected] == ["first-allow"]
        assert question.check_action("select", ()) is False
        assert question.check_action("selection_down", ()) is False
        await ui.until(lambda: view.prompt._ask is None, why="the question to close")

        result = asyncio.create_task(agent.permissions.request_permission(
            sessionId=agent.session_id,
            options=[schema.PermissionOption(option_id="modal-allow", name="Allow actual preview", kind="allow_once")],
            toolCall=schema.ToolCallUpdate(
                tool_call_id="action-preview", kind="edit", title="Actual preview",
                content=[schema.FileEditToolCallContent(
                    type="diff", path=str(Path(view.working_directory) / "action.txt"),
                    old_text="before", new_text="after")])))
        try:
            await ui.until(lambda: isinstance(app.screen, PermissionsScreen), why="the permission dialog")
            screen = app.screen
            await ui.until_shows("Allow actual preview")
            assert screen.check_action("reject_once", ()) is False
            await ui.press("r")
            assert not result.done()
            assert await pilot.click(screen.navigator, offset=(1, 0))
            await ui.press("a")
            assert not result.done()
            await ui.press("f9")
            answer = await asyncio.wait_for(result, 8)
            assert answer.outcome.option_id == "modal-allow"
            await ui.until(lambda: not isinstance(app.screen, PermissionsScreen), why="the dialog to close")
        finally:
            if not result.done():
                agent.permissions.cancel()
                await result

        # A newly declared question action gets its key, availability and effect with no other edit.
        class ReviewAction(QuestionAction):
            keys = {EditingMode: ("f8",)}

            def available(self, question):
                return question.accepts_selection

            async def apply(self, question):
                question.title = "DECLARATION_ONLY_REVIEW"

        class ReviewQuestion(Question):
            pass

        probe = ReviewQuestion("New case", options=[Answer("New option", "new-id")])
        await view.mount(probe)
        probe.focus()
        await ui.press("f8")
        assert probe.title == "DECLARATION_ONLY_REVIEW"
        await probe.remove()

        view.focus_prompt(scroll_end=False)
        assert ui.draft() == "KEEP_ACTION_DRAFT"
        assert view.prompt.prompt_text_area.document is document
        assert view.prompt.prompt_text_area.history is undo
        assert len(native.provider.requests) == 1
        assert not agent.permissions.pending


async def test_double_escape_cancels_a_running_native_turn(workspace, native_package):
    provider = ControlledProvider(request_budget=1, expected_disconnects=frozenset({1}))
    async with native_session(workspace, provider=provider) as native:
        ui = native.ui
        view = ui.conversation
        await ui.until_agent_ready()
        provider.hold_next_request()
        await ui.write_draft("ACTION_CANCEL_INPUT")
        await ui.press("enter")
        await ui.until(provider.entered.is_set, seconds=30, why="the input at the provider")
        await ui.until(lambda: view.turns.owner.busy, seconds=20, why="the running turn")
        assert view.check_action("cancel", ()) is True
        await ui.press("escape")
        assert view.turns.owner.busy
        assert "again" in str(view.query_one(Flash).render()).lower()
        await ui.press("escape")
        await ui.until(lambda: not native.executing, seconds=15, why="the turn to be cancelled")
        provider.release()
        assert len(provider.requests) == 1
        assert not native.agent.permissions.pending
