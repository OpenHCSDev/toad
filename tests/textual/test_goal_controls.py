"""Textual-facing: the goal bar mounts one control per declared interaction, paints them, and collapses."""

from support.goal_controls import goal_control
from agent_comms.planning.goal_actions import PausedGoalAction
from agent_comms.planning.goal_presentation import RunnableExecution

from toad.goal_interaction import GoalInteraction, GoalSession
from toad.goal_interactions.controls import CollapseInteraction
from toad.widgets.goal_bar import GoalBar, GoalControl
from support.goals import published_goal


class ProbeInteraction(GoalInteraction):
    label = "Probe"

    @classmethod
    async def apply(cls, session):
        session.view.prompt.text = "Declared control exercised"


async def show_goal(ui):
    view = ui.conversation
    goal = published_goal("Visible goal for control discovery", "new-control")
    view.goal_display = goal
    view.goal_execution = RunnableExecution(goal.id)
    bar = view.query_one(GoalBar)
    await ui.until(lambda: bar.controls.is_mounted, why="the shown goal bar's controls")
    return view, bar


async def test_every_declared_interaction_has_a_control_and_a_new_one_works(workspace):
    async with workspace.app(size=(140, 44)) as ui:
        _, pilot = ui.textual
        view, bar = await show_goal(ui)
        declared = set(GoalInteraction.members_with(GoalInteraction))
        assert {control.interaction for control in bar.query(GoalControl)} == declared
        control = goal_control(bar, ProbeInteraction)
        editor = view.prompt.prompt_text_area
        editor.focus()
        await ui.until(lambda: editor.has_focus, why="the composer to own input focus")
        assert await pilot.click(control)
        await ui.until(lambda: view.prompt.text == "Declared control exercised", why="the declared control to act")
        assert editor.has_focus, "Pointer goal actions must retain composer focus"
        view.prompt.text = ""
        control.focus()
        await ui.until(lambda: control.has_focus, why="keyboard focus on the goal action")
        await ui.press("enter")
        await ui.until(lambda: view.prompt.text == "Declared control exercised", why="keyboard activation of the same declared action")


async def test_collapsing_the_goal_bar_paints_expand_and_keeps_controls(workspace):
    async with workspace.app(size=(140, 44)) as ui:
        _, pilot = ui.textual
        _, bar = await show_goal(ui)
        await pilot.click(goal_control(bar, CollapseInteraction))
        await ui.until(lambda: bar.collapsed, why="the goal bar to collapse")
        await ui.until(lambda: ui.shows("Expand") and ui.shows("Probe"), why="Expand and Probe painted")


async def test_a_replaced_goal_session_refuses_the_old_binding(workspace):
    async with workspace.app(size=(140, 44)) as ui:
        view, _ = await show_goal(ui)
        old = view.goal_controls
        view.goal_controls = GoalSession(view)
        try:
            await old.change(PausedGoalAction)
        except ValueError as error:
            assert "presentation changed" in str(error)
        else:
            raise AssertionError("A retired binding may not control the replacement source")
        old.close()
        # The session stays bound to its conversation (dde3b616); closing retires its modal.
        assert old.modal is None
