"""The goal bar follows the real owner: standby, a long goal that scrolls, edits made elsewhere, pause/resume and clear."""

import asyncio
import json
import os

from agent_comms.child_process import ProcessIdentity
from agent_comms.goal_actions import (
    ActiveGoalAction,
    ClearGoalAction,
    EditGoalAction,
    GoalPrecondition,
    OwnerInvocable,
    PausedGoalAction,
    SetGoalAction,
    StandbyGoalAction,
)
from agent_comms.goal_presentation import IdleGoalExecution
from agent_comms.goal_scope import OneGoal
from agent_comms.goals import NoGoal
from agent_comms.threads import Thread
from rich.cells import cell_len
from support.native import ControlledProvider, native_session
from support.native_steps import goal_on_real_owner
from textual.containers import VerticalScroll
from textual.widgets import Static

from toad.screens.goal_details import GoalDetails
from toad.screens.goal_edit import GoalEdit
from toad.widgets.goal_bar import GoalBar, GoalControl, StandbyPulse

OBJECTIVE = "OBJECTIVE_BEGIN " + "Fully wrapped acceptance criteria. " * 40 + " OBJECTIVE_END"


def standing_by_for_a_peer(workspace):
    """Arrange the owner's goal to wait for a peer whose turn is running (this process plays the peer)."""
    def arrange(comms, session, goal):
        comms.registry.declare(Thread("peer", frozenset(), str(workspace.project),
                                      process_identity=ProcessIdentity.capture(os.getpid())))
        comms.agents.begin_turn("peer", "peer-turn-the-goal-waits-for")
        comms.goals.update_goal(session, StandbyGoalAction(
            wait_for=["peer"], progress="Progress details. " * 40 + " PROGRESS_END",
            expect=GoalPrecondition(goal_id=OneGoal(goal.id))))
    return arrange


def owner_edit(comms, session, text):
    current = comms.registry.require(session).goal
    comms.goals.update_goal(session, EditGoalAction(
        text=text, expect=GoalPrecondition(goal_id=OneGoal(current.id), expected_goal=current)), actor=OwnerInvocable)


async def test_standby_goal_pulses_and_its_long_text_scrolls_at_every_size(workspace, native_package):
    async with goal_on_real_owner(workspace, OBJECTIVE, size=(90, 35),
                                  arrange=standing_by_for_a_peer(workspace)) as native:
        ui = native.ui
        conversation = ui.conversation
        bar = conversation.query_one(GoalBar)
        await ui.until(lambda: "Standby" in str(bar.query_one(".goal-header", Static).render()),
                       why="the owner's standby execution")
        assert conversation.goal_display.snapshot.state.declared_name == "active"
        pulse = bar.query_one(StandbyPulse)
        assert pulse.active
        document = bar.query_one(".goal-document", VerticalScroll)
        assert document.max_scroll_y > 0
        assert document.size.height <= 7
        assert bar.region.bottom <= conversation.prompt.region.y
        document.scroll_end(animate=False)
        await ui.until_shows("PROGRESS_END")
        document.scroll_home(animate=False)
        await ui.until_shows("OBJECTIVE_BEGIN")
        for width, height in ((86, 28), (120, 40), (65, 22)):
            await ui.resize(width, height)
            document.scroll_end(animate=False)
            await ui.until_shows("PROGRESS_END")
            assert bar.region.y >= 0 and bar.region.bottom <= conversation.prompt.region.y
            assert all(control.region.y >= 0 and control.region.bottom <= height
                       for control in bar.query(GoalControl))
            document.scroll_home(animate=False)
            await ui.step()


async def test_edits_made_on_the_owner_reach_open_goal_screens_without_touching_a_draft(workspace, native_package):
    async with goal_on_real_owner(workspace, OBJECTIVE, size=(90, 35)) as native:
        ui, comms, session = native.ui, native.comms, native.thread
        app, pilot = ui.textual
        conversation = ui.conversation
        await pilot.click("#goal-history")
        await ui.until(lambda: isinstance(app.screen, GoalDetails), why="goal details")
        details = app.screen
        owner_edit(comms, session, "Changed through owner backend")
        await ui.until(lambda: details.goal_display.snapshot.text == "Changed through owner backend", seconds=6,
                       why="the owner's edit in goal details")
        assert "Changed through owner backend" in str(details.query_one("#goal-current-objective", Static).render())
        await ui.press("escape")
        await pilot.click("#goal-edit")
        await ui.until(lambda: isinstance(app.screen, GoalEdit), why="the goal editor")
        editor = app.screen
        editor.editor.text = "UNSAVED DRAFT"
        owner_edit(comms, session, "Concurrent owner edit")
        await ui.until(lambda: conversation.goal_display.snapshot.text == "Concurrent owner edit", seconds=6,
                       why="the concurrent edit in the goal bar")
        assert editor.editor.text == "UNSAVED DRAFT"


async def test_pause_resume_and_clear(workspace, native_package):
    async with goal_on_real_owner(workspace, OBJECTIVE, size=(90, 35),
                                  arrange=standing_by_for_a_peer(workspace)) as native:
        ui = native.ui
        conversation = ui.conversation
        bar = conversation.query_one(GoalBar)
        pulse = bar.query_one(StandbyPulse)
        await ui.until(lambda: pulse.active, why="the owner's standby execution")
        await conversation.goal_controls.change(PausedGoalAction)
        assert conversation.goal_display.snapshot.state.declared_name == "paused" and not pulse.active
        await conversation.goal_controls.change(ActiveGoalAction)
        assert conversation.goal_display.snapshot.state.declared_name == "active"

        await conversation.goal_controls.change(ClearGoalAction)
        assert conversation.goal_display.snapshot == NoGoal()
        assert conversation.goal_execution == IdleGoalExecution() and not bar.display


async def test_failed_ledger_repaints_retry_then_active_without_rewriting_goal(workspace, native_package):
    (workspace.project / "proof.txt").write_text("A real tool reads this file.\n")

    def reply(_request, number):
        if number == 1:
            return {"role": "assistant", "content": ""}, "stop"
        if number == 2:
            return {"role": "assistant", "tool_calls": [{
                "index": 0, "id": "p448-read", "type": "function",
                "function": {"name": "read", "arguments": json.dumps({"path": "proof.txt"})}}]}, "tool_calls"
        provider.hold_next_request()
        return {"role": "assistant", "content": "PRODUCTIVE_SUCCESSOR"}, "stop"

    provider = ControlledProvider(reply=reply, request_budget=4)
    async with native_session(workspace, provider=provider) as native:
        ui, agent, comms, session = native.ui, native.agent, native.comms, native.thread
        app, pilot = ui.textual
        view = ui.conversation
        view.prompt.text = "Keep the draft across the failed turn"
        bar = view.query_one(GoalBar)
        first = await agent.update_goal(SetGoalAction, OBJECTIVE)
        await ui.until(lambda: "Blocked" in str(bar.header.render()), seconds=30,
                       why="the unproductive native goal turn settles as failed")
        assert comms.registry.require(session).goal == first
        await ui.until(lambda: str(bar.query_one("#goal-toggle").render()) == "Retry",
                       why="Retry from execution while the stored goal remains active")
        await pilot.click("#goal-history")
        await ui.until(lambda: isinstance(app.screen, GoalDetails), why="the open goal details")
        details = app.screen
        sending = asyncio.create_task(agent.send_prompt("Read proof.txt and report completion"))
        try:
            await ui.until(sending.done, seconds=30, why="the fresh productive native input finishes")
            await sending
        finally:
            if not sending.done():
                sending.cancel()
            await asyncio.gather(sending, return_exceptions=True)
        assert comms.registry.require(session).goal == first
        await ui.until(lambda: "Active" in str(details.query_one("#goal-current-heading", Static).render()),
                       why="the already-open details following productive settlement")
        await ui.press("escape")
        await ui.until(lambda: str(bar.query_one("#goal-toggle").render()) == "Pause",
                       why="the goal control following the ledger-only change")
        assert view.prompt.text == "Keep the draft across the failed turn"


async def test_standby_goal_mention_opens_its_peer_and_returns_to_the_draft(workspace, native_package):
    async with native_session(workspace) as native:
        ui, comms = native.ui, native.comms
        owner = comms.registry.require(native.thread)
        comms.registry.declare(Thread(
            "peer", frozenset(), str(native.project), model=owner.model,
            thinking_level=owner.thinking_level,
        ))
        await asyncio.to_thread(comms.owners.start, "peer")
        goal = comms.goals.update_goal(native.thread, SetGoalAction(text="Coordinate with @peer"))
        comms.goals.update_goal(native.thread, StandbyGoalAction(
            wait_for=("peer",), expect=GoalPrecondition(goal_id=OneGoal(goal.id))))
        original = ui.selected_tab
        await ui.write_draft("Composer draft stays")
        await ui.until_shows("Coordinate with @peer")
        summary = ui.conversation.goal_bar.summary
        offset = (cell_len(summary.goal_text.split("@peer")[0]), 0)
        await ui.until(lambda: ui.app.screen.get_style_at(
            summary.region.x + offset[0], summary.region.y,
        ).meta.get("@click") is not None, why="the objective's bound goal mention")
        assert await ui.pilot.click(summary, offset=offset)
        await ui.until(lambda: ui.app.selected_session.thread_identity.thread_name() == "peer",
                       why="the goal mention opens its peer")
        await ui.select_tab(original)
        assert ui.draft() == "Composer draft stays"
