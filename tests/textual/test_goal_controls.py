"""Textual-facing: the goal bar mounts one control per declared interaction, paints them, and collapses."""

from agent_comms.goal_actions import PausedGoalAction

from toad.goal_interaction import GoalInteraction, GoalSession
from toad.widgets.goal_bar import GoalBar, GoalControl
from support.goals import published_goal


class ProbeInteraction(GoalInteraction):
    label = "Probe"

    @classmethod
    async def apply(cls, session):
        session.view.prompt.text = "Declared control exercised"


async def show_goal(ui):
    view = ui.conversation
    view.goal_display = published_goal("Visible goal for control discovery", "new-control")
    await ui.until(lambda: view.query(GoalBar), why="the goal bar")
    return view, view.query_one(GoalBar)


async def test_every_declared_interaction_has_a_control_and_a_new_one_works(workspace):
    async with workspace.app(size=(140, 44)) as ui:
        _, pilot = ui.textual
        view, bar = await show_goal(ui)
        declared = {control.control_id() for control in GoalInteraction.members_with(GoalInteraction)}
        assert {control.id for control in bar.query(GoalControl)} == declared
        await pilot.click("#" + ProbeInteraction.control_id())
        await ui.until(lambda: view.prompt.text == "Declared control exercised", why="the declared control to act")


async def test_collapsing_the_goal_bar_paints_expand_and_keeps_controls(workspace):
    async with workspace.app(size=(140, 44)) as ui:
        _, pilot = ui.textual
        _, bar = await show_goal(ui)
        await pilot.click("#goal-collapse")
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
