"""The goal bar follows the real owner: standby, a long goal that scrolls, edits made elsewhere, pause/resume and clear."""

import os
from contextlib import AsyncExitStack

from agent_comms import agent_events as events
from agent_comms.owned_turn import OwnedTurn
from agent_comms.child_process import ProcessIdentity
from agent_comms.goal_actions import (
    ActiveGoalAction, ClearGoalAction, EditGoalAction, GoalPrecondition, OwnerInvocable, PausedGoalAction,
    StandbyGoalAction,
)
from agent_comms.goal_presentation import IdleGoalExecution
from agent_comms.goals import NoGoal
from textual.containers import VerticalScroll
from textual.widgets import Static

from support.native_steps import goal_on_real_owner
from toad.screens.goal_details import GoalDetails
from toad.screens.goal_edit import GoalEdit
from toad.widgets.goal_bar import GoalBar, GoalControl, StandbyPulse
from toad.widgets.throbber import Throbber

OBJECTIVE = "OBJECTIVE_BEGIN " + "Fully wrapped acceptance criteria. " * 40 + " OBJECTIVE_END"


def standing_by_for_a_peer(workspace):
    """Arrange the owner's goal to wait for a peer whose turn is running (this process plays the peer)."""
    def arrange(comms, session, goal):
        comms.registry.declare(comms.registry.new_thread("peer", frozenset(), str(workspace.project),
                                      process_identity=ProcessIdentity.capture(os.getpid())))
        comms.agents.begin_turn("peer", "peer-turn-the-goal-waits-for")
        comms.goals.update_goal(session, StandbyGoalAction(
            wait_for=["peer"], progress="Progress details. " * 40 + " PROGRESS_END",
            expect=GoalPrecondition(goal_id=goal.id)))
    return arrange


def owner_edit(comms, session, text):
    current = comms.registry.require(session).goal
    comms.goals.update_goal(session, EditGoalAction(
        text=text, expect=GoalPrecondition(goal_id=current.id, expected_goal=current)), actor=OwnerInvocable)


async def test_standby_goal_pulses_and_its_long_text_scrolls_at_every_size(workspace, native_package):
    async with goal_on_real_owner(workspace, native_package, OBJECTIVE, size=(90, 35),
                                  arrange=standing_by_for_a_peer(workspace)) as (ui, _agent, _owner, _session, _goal):
        conversation = ui.conversation
        bar = conversation.query_one(GoalBar)
        await ui.until(lambda: "Standby" in str(bar.query_one(".goal-header", Static).render()),
                       why="the owner's standby execution")
        assert conversation.goal_display.snapshot.state.declared_name == "active"
        pulse = bar.query_one(StandbyPulse)
        assert pulse.active
        conversation.busy_count += 1  # the activity indicator is computed from this and the turn
        await ui.until(lambda: conversation.query_one(Throbber).busy, why="the activity indicator")
        assert pulse.active, "A busy activity indicator hid the owner's standby"
        conversation.busy_count -= 1
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
    async with goal_on_real_owner(workspace, native_package, OBJECTIVE, size=(90, 35)) as (
            ui, _agent, owner, session, _goal):
        comms = owner.comms
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
    async with goal_on_real_owner(workspace, native_package, OBJECTIVE, size=(90, 35),
                                  arrange=standing_by_for_a_peer(workspace)) as (ui, _agent, _owner, _session, _goal):
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
    async with goal_on_real_owner(workspace, native_package, OBJECTIVE) as (
            ui, _agent, owner, session, first):
        app, pilot = ui.textual
        view = ui.conversation
        view.prompt.text = "Keep the draft across the failed turn"
        bar = view.query_one(GoalBar)
        failed = OwnedTurn(owner.turns, session, session, "Original work", original_goal_id=first.id)
        async with AsyncExitStack() as resources, AsyncExitStack() as permits:
            assert await failed.acquire(resources, permits)
            await failed.progress.done(events.Done("Controlled backend failure", False))
        assert owner.comms.registry.require(session).goal == first
        await view.goal_observation.refresh()
        await ui.until(lambda: "Blocked" in str(bar.header.render()), why="the failed ledger in the heading")
        await ui.until(lambda: str(bar.query_one("#goal-toggle").render()) == "Retry",
                       why="Retry from execution while the stored goal remains active")
        await pilot.click("#goal-history")
        await ui.until(lambda: isinstance(app.screen, GoalDetails), why="the open goal details")
        details = app.screen
        successor = OwnedTurn(owner.turns, session, session, "Fresh productive input",
                              original_goal_id=first.id, original_owner_input=True)
        async with AsyncExitStack() as resources, AsyncExitStack() as permits:
            assert await successor.acquire(resources, permits)
            await successor.progress.tool_ended(events.ToolEnd("read", "read", True, "Source read"))
            await successor.progress.done(events.Done("Productive successor", True))
        assert owner.comms.registry.require(session).goal == first
        await view.goal_observation.refresh()
        await ui.until(lambda: "Active" in str(details.query_one("#goal-current-heading", Static).render()),
                       why="the already-open details following productive settlement")
        await ui.press("escape")
        await ui.until(lambda: str(bar.query_one("#goal-toggle").render()) == "Pause",
                       why="the goal control following the ledger-only change")
        assert view.prompt.text == "Keep the draft across the failed turn"
