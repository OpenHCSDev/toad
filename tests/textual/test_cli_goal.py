"""Textual-facing: a CLI thread's goal is the one the bus holds for its inbox. Its mailbox view
shows it in the goal bar, and the bar's controls change it through Core, which wakes the CLI
through its inbox when the goal becomes active, as a nudge does."""

from agent_comms.planning.goal_actions import SetGoalAction
from agent_comms.planning.goal_states import PausedGoal
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.threads import ExternalThread

from support.goal_controls import goal_control
from toad.goal_interactions.controls import ToggleInteraction
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.goal_bar import GoalBar

CLI = "cli-goal"


async def open_cli(ui):
    app, _ = ui.textual
    sidebar = app.workspace_chrome.channels
    if sidebar.collapsed:
        sidebar.toggle()
    tree = sidebar.query_one(CommsSidebar)
    await ui.until(lambda: "#team" in tree.groups, why="the CLI's channel group")
    group = tree.groups["#team"]
    if not group.expanded:
        group.toggle_members()
    await ui.until(lambda: CLI in group.rows, why="the CLI's row")
    group.rows[CLI].open_selected()
    await ui.until(lambda: app.selected_session is not None
                   and app.selected_session.thread_identity.thread_name() == CLI,
                   why="the CLI's tab")
    await app.selected_session.wait_content_ready()
    return ui.conversation


async def test_a_cli_goal_shows_in_its_mailbox_and_its_controls_change_it_on_the_bus(workspace):
    comms = workspace.comms
    comms.registry.declare(ExternalThread(CLI, frozenset({"team"}), Checkout(workspace.project)))
    comms.goals.update_goal(CLI, SetGoalAction(text="Land the bus-held goal"))
    goal = lambda: comms.registry.require(CLI).goal.require()
    async with workspace.app(session=False) as ui:
        _, pilot = ui.textual
        view = await open_cli(ui)
        await ui.until(lambda: view.goal_display.visible, why="the bus-held goal read into the mailbox view")
        await ui.until_shows("Land the bus-held goal")
        bar = view.query_one(GoalBar)
        await ui.until(lambda: goal_control(bar, ToggleInteraction).display, why="the pause control")
        await pilot.click(goal_control(bar, ToggleInteraction))
        await ui.until(lambda: isinstance(goal().state, PausedGoal), why="the bus goal paused by the owner's control")
        woken = comms.bus.pending_count(CLI)
        await ui.until(lambda: "Resume" in ui.painted(bar), why="the paused goal's resume control")
        await pilot.click(goal_control(bar, ToggleInteraction))
        await ui.until(lambda: not isinstance(goal().state, PausedGoal), why="the bus goal resumed")
        await ui.until(lambda: comms.bus.pending_count(CLI) > woken,
                       why="the resumed goal wakes the CLI through its inbox")
        comms.goals.update_goal(CLI, SetGoalAction(text="A goal changed elsewhere"))
        await ui.until_shows("A goal changed elsewhere")
