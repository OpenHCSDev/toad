"""Saved-history UI goal controls follow actual runtime-owner changes."""

import asyncio
from dataclasses import replace
from uuid import uuid4

from agent_comms.goal_actions import ClearGoalAction, EditGoalAction, OwnerInvocable
from agent_comms.goal_states import CompletedGoal
from agent_comms.goals import Goal
from textual.widgets import Static
from textual.widgets import Input

from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp
from saved_state_user_journey_pilot import click_tab, click_thread, prepare_saved_state, screen_paint, submit_editor
from toad.screens.goal_edit import GoalEdit
from toad.screens.goal_details import GoalDetails
from toad.widgets.goal_bar import GoalBar
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.comms_sidebar import CommsRow
from toad.thread_actions import ForkAction
from runtime_fixture import wait_channel_roster, wait_fork_dialog
from manual_live_turn_status import require_current_activity


def seed_goal(comms, text, name="beta"):
    owner = comms.registry.require(name)
    goal = Goal(text=text, id=uuid4().hex, state=CompletedGoal())
    comms.registry.register(replace(owner, goal=goal), comms.registry.status(owner.name))
    return goal


async def prepare_state(*args):
    await prepare_saved_state(*args)
    seed_goal(args[0], "INITIAL_SAVED_GOAL")


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    bar = view.query_one(GoalBar)
    await until(pilot, lambda: view.goal_display.snapshot is not None)
    await until(pilot, lambda: "INITIAL_SAVED_GOAL" in screen_paint(app))
    print("SAVED_GOAL_ACTUAL_PAINT", flush=True)
    assert await pilot.click("#goal-history")
    await until(pilot, lambda: isinstance(app.screen, GoalDetails))
    await until(pilot, lambda: "INITIAL_SAVED_GOAL" in screen_paint(app))
    await pilot.press("escape")
    print("PHYSICAL_GOAL_HISTORY_CURRENT_SOURCE_AND_REVISIONS", flush=True)
    first = app.selected_session
    await click_thread(app, pilot, "gamma")
    await click_tab(app, pilot, first.id)
    await until(pilot, lambda: "INITIAL_SAVED_GOAL" in screen_paint(app))
    print("GOAL_RETURN_ACTUAL_AGENT_TAB_CLICK", flush=True)

    # A backend clear must remove the controls in the already open tab.
    comms.goals.update_goal("beta", ClearGoalAction(), actor=OwnerInvocable)
    try:
        await until(pilot, lambda: view.goal_display.snapshot is None and not bar.display, 5)
    except TimeoutError:
        print("STALE_GOAL", view.goal_display, bar.goal_display, bar.display,
              view.goal_observation.view is view, view.goal_observation.active,
              str(bar.query_one(".goal-header", Static).render()), flush=True)
        raise
    assert "INITIAL_SAVED_GOAL" not in screen_paint(app)
    print("BACKEND_CLEAR_AUTO_REMOVED_OPEN_TAB_GOAL", flush=True)

    goal = seed_goal(comms, "BUTTON_CLEAR_GOAL")
    await until(pilot, lambda: view.goal_display.snapshot == goal and bar.display)
    assert await pilot.click("#goal-clear")
    await until(pilot, lambda: comms.registry.require("beta").goal is None and not bar.display)
    assert "refresh its state" not in screen_paint(app)
    print("PHYSICAL_CLEAR_BUTTON_BACKEND_AND_UI_SETTLED", flush=True)

    goal = seed_goal(comms, "EDIT_GOAL")
    await until(pilot, lambda: view.goal_display.snapshot == goal and bar.display)
    assert await pilot.click("#goal-edit")
    await until(pilot, lambda: isinstance(app.screen, GoalEdit))
    editor = app.screen
    editor.editor.text = "DRAFT_SURVIVES_CONCURRENT_GOAL_CLEAR"
    comms.goals.update_goal("beta", ClearGoalAction(), actor=OwnerInvocable)
    assert await pilot.click("#goal-save")
    await until(pilot, lambda: view.goal_display.snapshot is None)
    assert editor.editor.text == "DRAFT_SURVIVES_CONCURRENT_GOAL_CLEAR"
    assert "refresh its state" not in screen_paint(app)
    await pilot.press("escape")
    assert not bar.display
    assert len(requests) == 2, "Goal controls started or replayed a native input"
    print("CONCURRENT_CLEAR_EDIT_RECONCILES_WITHOUT_OVERWRITE_OR_LOST_DRAFT", flush=True)

    sidebar = await wait_channel_roster(app, pilot, "#team")
    row = next(row for row in sidebar.query(CommsRow) if row.target_name == "beta")
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(row, button=3)
    await until(pilot, lambda: bool(app.screen.query(ContextMenuItem)))
    fork = next(item for item in app.screen.query(ContextMenuItem)
                if item.action == ForkAction.declared_name)
    assert await pilot.click(fork)
    dialog = await wait_fork_dialog(app, pilot)
    dialog.query_one("#fork-name", Input).value = "goal-child"
    assert dialog.query_one("#fork-tags", Input).value == "team"
    assert await pilot.click("#fork-create")
    await until(pilot, lambda: "goal-child" in comms.registry.all_threads())
    child_screen = await click_thread(app, pilot, "goal-child")
    await until(pilot, lambda: comms.registry.require("goal-child").process_alive)
    child = comms.registry.require("goal-child")
    assert child.tags == comms.registry.require("beta").tags
    from psutil import Process
    assert "AGENT_COMMS_STARTUP_INPUT_KEY" not in Process(child.pid).environ()
    assert not child.executing
    assert len(requests) == 2, "A fork without a task admitted a native input"
    goal = seed_goal(comms, "CHILD_ONLY_GOAL", "goal-child")
    child_view = child_screen.conversation
    await until(pilot, lambda: child_view.goal_display.snapshot == goal)
    await until(pilot, lambda: "CHILD_ONLY_GOAL" in screen_paint(app))
    await click_tab(app, pilot, first.id)
    parent_view = first.conversation
    await until(pilot, lambda: parent_view.goal_display.snapshot is None)
    assert not parent_view.query_one(GoalBar).display
    assert "CHILD_ONLY_GOAL" not in screen_paint(app)
    require_current_activity(first)
    gamma = await click_thread(app, pilot, "gamma")
    assert gamma.conversation.goal_display.snapshot is None
    assert not gamma.conversation.query_one(GoalBar).display
    await click_tab(app, pilot, child_screen.id)
    assert child_screen.conversation.goal_display.snapshot == goal
    assert child_screen.conversation.query_one(GoalBar).goal_display is child_screen.conversation.goal_display
    await click_tab(app, pilot, first.id)
    assert first.conversation.goal_display.snapshot is None
    assert not first.conversation.query_one(GoalBar).display
    assert len(requests) == 2
    print("PHYSICAL_IDLE_FORK_INHERITED_TAGS_CHILD_PARENT_UNRELATED_GOAL_ISOLATION", flush=True)
    await click_tab(app, pilot, child_screen.id)
    child_view = child_screen.conversation
    await submit_editor(pilot, child_view.prompt.prompt_text_area, "AFTER_COMPLETED_GOAL_INPUT")
    await until(pilot, lambda: len(requests) == 3)
    await until(pilot, lambda: comms.registry.require("goal-child").executing is False)
    await until(pilot, lambda: "NATIVE_RESPONSE_3" in screen_paint(app))
    assert comms.registry.require("goal-child").goal == goal
    assert child_view.queue_projection.status == "available"
    require_current_activity(child_screen)
    print("COMPLETED_GOAL_IDLE_FORK_ACCEPTS_REAL_EDITOR_MESSAGE_AND_SETTLES", flush=True)


if __name__ == "__main__":
    asyncio.run(native_fixture(app_type=InstalledApp, prepare_state=prepare_state,
                              acceptance=acceptance))
