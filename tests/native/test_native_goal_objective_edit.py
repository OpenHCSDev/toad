"""Editing a goal's objective in Toad saves through the real owner and redraws the goal bar; progress stays separate."""

from agent_comms.acp_extension import GoalChangedUpdate
from agent_comms.goal_actions import ActiveGoalAction, GoalPrecondition
from agent_comms.goal_scope import OneGoal
from support.native_steps import goal_on_real_owner
from textual.widgets import Static

from toad.core.events import CommsUpdated
from toad.screens.goal_details import GoalDetails
from toad.screens.goal_edit import GoalEdit
from toad.widgets.goal_text import GoalText

OBJECTIVE = "Work on draft PR #17 and report remaining gaps. " + "Detailed acceptance criteria. " * 30


def with_progress(comms, session, goal):
    comms.goals.update_goal(session, ActiveGoalAction(
        progress="Renamed parent thread to pr17 and forked implementation.",
        expect=GoalPrecondition(goal_id=OneGoal(goal.id))))


def goal_in_toad(workspace):
    return goal_on_real_owner(workspace, OBJECTIVE, arrange=with_progress)


async def test_objective_edits_save_to_the_owner_and_redraw_the_goal_bar(workspace, native_package):
    async with goal_in_toad(workspace) as native:
        ui, agent, comms, session = native.ui, native.agent, native.comms, native.thread
        first = comms.registry.require(session).goal.require()
        app, pilot = ui.textual
        conversation = ui.conversation
        current = first
        for objective in ("Short updated goal", "Second short goal"):
            await pilot.click("#goal-edit")
            await ui.until(lambda: isinstance(app.screen, GoalEdit), why="the goal editor")
            editor = app.screen
            assert editor.editor.text == comms.registry.require(session).goal.text
            assert "Renamed parent thread" not in editor.editor.text
            assert "Progress (read-only): Renamed parent thread" in str(
                editor.query_one(".goal-edit-progress", Static).render())
            editor.editor.prompt_text_area.focus()
            await ui.step()
            editor.editor.prompt_text_area.action_select_all()
            await ui.press("backspace", *list(objective))
            assert editor.editor.text == objective, repr(editor.editor.text)
            if objective.startswith("Second"):
                await ui.press("enter")
            else:
                await pilot.click("#goal-save")
            await ui.until(lambda: not isinstance(app.screen, GoalEdit), why="the editor to close")
            await ui.until(lambda expected=objective: comms.registry.require(session).goal.text == expected, why="the saved objective")
            current = comms.registry.require(session).goal
            assert current.id == first.id
            await ui.until(lambda expected=current: conversation.goal_display.snapshot == expected, why="the saved goal in the bar")
            summary = conversation.query_one(".goal-summary", GoalText)
            assert objective in str(summary.render()), str(summary.render())
            assert ui.shows(" ".join(objective.split()[:3])) and ui.shows(objective.split()[-1])
            assert ui.shows("Objective:") and ui.shows("Progress:")
            assert ui.shows("Renamed parent thread")

        long_objective = ("Work on draft PR #17. " + "Preserve detailed acceptance criteria. " * 30
                          + "TAIL_COORDINATOR")
        current = await agent.edit_goal(current, long_objective)
        await conversation.goal_observation.refresh()
        await ui.until_shows(f"rev {current.revision}")
        assert not ui.shows("Scroll for full text") and not ui.shows("TAIL_COORDINATOR")
        await pilot.click("#goal-history")
        await ui.until(lambda: isinstance(app.screen, GoalDetails), why="goal details")
        assert "TAIL_COORDINATOR" in app.screen.goal_display.snapshot.text
        await ui.until_shows("Objective: Work on draft PR #17.")


async def test_a_late_notice_of_an_older_goal_does_not_replace_the_current_one(workspace, native_package):
    async with goal_in_toad(workspace) as native:
        ui, agent = native.ui, native.agent
        conversation = ui.conversation
        before = await agent.get_goal_snapshot()
        older = before.goal.require()
        current = await agent.edit_goal(older, "Short updated goal")
        await conversation.goal_observation.refresh()
        assert conversation.goal_display.snapshot == current
        shown = []
        conversation.watch(conversation, "goal_display", lambda display: shown.append(display.snapshot), init=False)
        agent.events.publish(CommsUpdated(GoalChangedUpdate(older, before.execution), session_id=agent.session_id))
        await ui.step(1)
        assert older not in shown, (
            f"A notice of revision {older.revision} was shown over revision {current.revision}")
        assert conversation.goal_display.snapshot == current
