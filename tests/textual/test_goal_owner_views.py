"""Textual-facing: goal bar standby row, goal edit screen and goal details screen as Textual widgets over a scripted goal owner."""

import asyncio
from dataclasses import replace

from agent_comms.acp_extension import GoalChangedUpdate
from agent_comms.field_codec import TurnId
from agent_comms.goal_failure_observation import FailedTurnEvidence
from agent_comms.goal_history import (
    RecordedGoalRevision, BaselineRevision, TransitionRevision, ObservedGapRevision,
)
from agent_comms.goal_presentation import (
    GoalWaitTarget, IdleGoalExecution, PausedExecution, RunnableExecution, StandbyExecution,
)
from agent_comms.goal_states import PausedGoal
from agent_comms.goals import NoGoal
from agent_comms.repo import Checkout
from agent_comms.runtime_requests import GoalHistoryReply
from agent_comms.thread_identity import RecordedThreadIncarnation
from agent_comms.turn_failure import NativeChildSignaled
from textual.widgets import Button, Static

from support.goals import ScriptedGoalOwner, bound_mentions, published_goal
from support.agents import RecordedEvents
from support.textual_steps import channel_roster
from toad.core.events import CommsUpdated
from toad.core.input_events import SelectTarget
from toad.screens.goal_details import GoalDetails
from toad.screens.goal_edit import GoalEdit
from toad.widgets.goal_bar import GoalBar


def goal_owner(workspace, app):
    goal = bound_mentions(published_goal("Coordinate with @peer", "stable-goal", progress="Keep evidence", revision=4),
                          workspace.thread("goal-owner"), workspace.comms.registry.snapshot())
    execution = StandbyExecution(goal.id, (GoalWaitTarget(RecordedThreadIncarnation("peer", 1.0)),), ())
    baseline = replace(goal, text="HISTORICAL_OBJECTIVE", revision=1)
    transitioned = replace(goal, revision=2)
    history = GoalHistoryReply((
        RecordedGoalRevision(sequence=1, kind=BaselineRevision, observed_at=1000.0, before=NoGoal(),
                             after=baseline),
        RecordedGoalRevision(sequence=2, kind=TransitionRevision, observed_at=1001.0,
                             before=baseline, after=transitioned),
        RecordedGoalRevision(sequence=3, kind=ObservedGapRevision, observed_at=1002.0,
                             before=transitioned, after=goal),
    ), (FailedTurnEvidence(
        attempt_id="attempt-1", goal_id=goal.id, generation=3, owner="goal-owner", owner_created_at=1.0,
        worktree="/work", claim_generation=1, turn_generation=1, goal_revision=4, turn_id=TurnId.mint(),
        failure=NativeChildSignaled,
    ),))
    owner = ScriptedGoalOwner.owning(app, goal, execution, history=history)
    owner.reject = True
    return owner


async def shown_goal(workspace, ui):
    workspace.thread("peer")
    await channel_roster(ui, "#all")
    owner = goal_owner(workspace, ui.app)
    ui.attach_agent(owner)
    screen = ui.app.selected_session
    await workspace.bind(screen, "goal-owner")
    view = ui.conversation
    view.goal_display = owner.goal
    view.goal_execution = owner.execution
    view.prompt.text = "Composer draft stays"
    bar = view.query_one(GoalBar)
    status = bar.query_one(".goal-execution", Static)
    await ui.until(lambda: status.display, why="the standby row")
    return owner, view, bar, status


async def refresh_goal(ui, view):
    await view.goal_observation.refresh()
    await ui.step()


async def test_standby_row_names_the_waited_peer_and_mentions_navigate(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        owner, view, bar, status = await shown_goal(workspace, ui)
        assert "Standby" in str(status.render()) and "@peer" in str(status.render())
        original = ui.selected_tab
        await ui.until_shows("Coordinate with @peer")
        await ui.until(lambda: ui.link_at("@peer", occurrence=1) is not None,
                       why="the observed goal mention becomes a navigation link")
        opened = RecordedEvents()
        subscription = bar.summary.core_publications.subscribe(SelectTarget, opened.receive)
        assert await ui.pilot.click(bar.summary, offset=(bar.summary.goal_text.index("@peer"), 0))
        await ui.step()
        await ui.until(lambda: bool(opened), why="the clicked goal mention emits its target")
        assert opened[-1].target.name == "peer"
        subscription.close()
        await ui.until(lambda: ui.app.selected_session.thread_identity.thread_name() == "peer",
                       why="the goal mention opens the named peer")
        await ui.select_tab(original)
        assert view.prompt.text == "Composer draft stays"


async def test_standby_is_never_inferred_from_the_goal_text_or_a_paused_goal(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        owner, view, bar, status = await shown_goal(workspace, ui)
        standby_execution = owner.execution
        owner.execution = RunnableExecution(owner.goal.id)
        await refresh_goal(ui, view)
        await ui.until(lambda: not status.display, why="the standby row hidden when the owner says runnable")
        active_goal = owner.goal
        pause = PausedGoal()
        owner.goal = replace(owner.goal, state=pause)
        owner.execution = PausedExecution(owner.goal.id, pause.source)
        await refresh_goal(ui, view)
        await ui.until(lambda: not status.display, why="the owner's paused execution")
        owner.goal = active_goal
        owner.execution = standby_execution
        await refresh_goal(ui, view)
        await ui.until(lambda: status.display, why="the standby row back")


async def test_rejected_goal_edit_keeps_the_draft_and_the_retry_is_accepted(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        app, pilot = ui.textual
        owner, view, bar, status = await shown_goal(workspace, ui)
        await ui.until_shows("Edit")
        await pilot.click("#goal-edit")
        await ui.until(lambda: isinstance(app.screen, GoalEdit), why="the goal editor")
        editor = app.screen
        editor.query_one("#goal-save", Button).active_effect_duration = 0
        editor.editor.text = "Ask @pe"
        editor.editor.prompt_text_area.move_cursor((0, 7))
        editor.editor.refresh_mentions(force=True)
        assert editor.editor._options[0].name == "peer"
        editor.editor.accept_mention()
        assert editor.editor.text == "Ask @peer "
        await ui.step()
        await pilot.click("#goal-save")
        await ui.until(lambda: "Goal changed" in str(editor.query_one("#goal-edit-error", Static).render()),
                       why="the rejection message in the editor")
        assert app.screen is editor
        assert view.goal_display.snapshot.text == "Coordinate with @peer"
        assert editor.editor.text == "Ask @peer ", "Rejected edit keeps user's draft"
        owner.reject = False
        await pilot.click("#goal-save")
        await ui.until(lambda: not isinstance(app.screen, GoalEdit), why="the editor closed after acceptance")
        await ui.until(lambda: view.goal_display.snapshot.revision == 5, why="the edited goal shown")
        assert view.goal_display.snapshot.id == "stable-goal"
        assert owner.requests == [("edit", ("stable-goal", 4, "Ask @peer"))] * 2
        assert view.prompt.text == "Composer draft stays"


async def test_goal_editor_cannot_close_while_its_save_is_in_flight(workspace):
    started, release = asyncio.Event(), asyncio.Event()

    async def save(text):
        started.set()
        await release.wait()

    async with workspace.app(size=(100, 35)) as ui:
        editor = GoalEdit(published_goal("Keep objective", "saving-goal"),
                          project=Checkout(workspace.project), on_save=save)
        await ui.app.push_screen(editor)
        worker = ui.app.run_worker(editor.save("Updated objective"))
        await started.wait()
        await ui.press("escape")
        assert ui.app.screen is editor and editor.saving
        await ui.pilot.click("#goal-cancel")
        await ui.step()
        assert ui.app.screen is editor and editor.saving
        release.set()
        await worker.wait()
        await ui.until(lambda: ui.app.screen is not editor,
                       why="the accepted save closes its editor")


async def test_goal_history_lists_earlier_revisions(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        app, pilot = ui.textual
        owner, view, bar, status = await shown_goal(workspace, ui)
        await ui.until_shows("History")
        await pilot.click("#goal-history")
        await ui.until(lambda: isinstance(app.screen, GoalDetails), why="the goal details screen")
        for text in ("HISTORICAL_OBJECTIVE", "baseline", "transition", "observed gap",
                     "Attempt 3 · revision 4 · native child signaled"):
            await ui.until_shows(text)
        await ui.press("escape")
        assert view.prompt.text == "Composer draft stays"


async def test_owner_pushes_replace_and_then_remove_the_goal(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        owner, view, bar, status = await shown_goal(workspace, ui)
        pushed = replace(owner.goal, text="Backend edited the same goal", revision=6)
        owner.goal = pushed
        owner.events.publish(CommsUpdated(GoalChangedUpdate(pushed, owner.execution), owner.session_id))
        await ui.until(lambda: view.goal_display.snapshot == pushed, why="the pushed goal")
        await ui.until(lambda: "Backend edited the same goal" in str(bar.query_one(".goal-summary", Static).render()),
                       why="the pushed text in the bar")
        owner.goal, owner.execution = NoGoal(), IdleGoalExecution()
        owner.events.publish(CommsUpdated(GoalChangedUpdate(NoGoal(), IdleGoalExecution()), owner.session_id))
        await ui.until(lambda: view.goal_display.snapshot == NoGoal() and view.goal_execution == IdleGoalExecution(),
                       why="the goal removed")
        await ui.until(lambda: not bar.display, why="the bar hidden")
