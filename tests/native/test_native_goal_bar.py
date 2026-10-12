"""The goal bar follows the real owner: standby, a long goal that scrolls, edits made elsewhere, an owner outage."""

import asyncio
import os
import threading

from agent_comms.child_process import ProcessIdentity
from agent_comms.goal_actions import (
    ActiveGoalAction, ClearGoalAction, EditGoalAction, GoalPrecondition, OwnerInvocable, PausedGoalAction,
    StandbyGoalAction,
)
from agent_comms.threads import Thread
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
        comms.registry.declare(Thread("peer", frozenset(), str(workspace.project),
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
                                  arrange=standing_by_for_a_peer(workspace)) as (ui, _agent, _comms, _session, _goal):
        conversation = ui.conversation
        await ui.until(lambda: conversation.goal_execution is not None, why="the goal's execution state")
        bar = conversation.query_one(GoalBar)
        assert "Standby" in str(bar.query_one(".goal-header", Static).render())
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
            ui, _agent, comms, session, _goal):
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


async def test_pause_resume_owner_outage_and_clear(workspace, native_package):
    async with goal_on_real_owner(workspace, native_package, OBJECTIVE, size=(90, 35),
                                  arrange=standing_by_for_a_peer(workspace)) as (ui, _agent, comms, _session, _goal):
        conversation = ui.conversation
        await ui.until(lambda: conversation.goal_execution is not None, why="the goal's execution state")
        bar = conversation.query_one(GoalBar)
        pulse = bar.query_one(StandbyPulse)
        await conversation.goal_controls.change(PausedGoalAction)
        assert conversation.goal_display.snapshot.state.declared_name == "paused" and not pulse.active
        await conversation.goal_controls.change(ActiveGoalAction)
        assert conversation.goal_display.snapshot.state.declared_name == "active"

        # An owner that cannot be read marks the kept goal unavailable; it is never shown as standby.
        read = comms.goals.goal_snapshot

        def unavailable(_name):
            raise OSError("Owner temporarily unavailable")

        comms.goals.goal_snapshot = unavailable
        try:
            await ui.until(lambda: not conversation.goal_display.can_control, seconds=6, why="the goal marked unavailable")
            assert "unavailable" in str(bar.query_one(".goal-header", Static).render())
            assert not pulse.active
            assert all(control.disabled for control in bar.query(GoalControl) if control.id != "goal-collapse")
            assert not bar.query_one("#goal-collapse", GoalControl).disabled
        finally:
            comms.goals.goal_snapshot = read
        await ui.until(lambda: conversation.goal_display.can_control, seconds=6, why="the goal controllable again")
        await conversation.goal_controls.change(ClearGoalAction)
        assert conversation.goal_display.snapshot is None and not bar.display


async def test_a_goal_read_from_a_stalled_owner_gives_up(workspace, native_package):
    async with goal_on_real_owner(workspace, native_package, OBJECTIVE, size=(90, 35)) as (
            _ui, agent, comms, _session, _goal):
        read = comms.goals.goal_snapshot
        release = threading.Event()

        def stalled(name):
            release.wait(10)
            return read(name)

        comms.goals.goal_snapshot = stalled
        try:
            try:
                await asyncio.wait_for(agent.get_goal_snapshot(), 3.5)
            except TimeoutError:
                pass
            else:
                raise AssertionError("The goal read did not time out")
        finally:
            release.set()
            comms.goals.goal_snapshot = read
