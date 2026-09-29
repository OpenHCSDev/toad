"""Saved-history UI goal controls follow actual runtime-owner changes."""

import asyncio
from dataclasses import replace
from uuid import uuid4

from agent_comms.goal_actions import ClearGoalAction, EditGoalAction, OwnerInvocable
from agent_comms.goal_states import CompletedGoal
from agent_comms.goals import Goal
from textual.widgets import Static

from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp
from saved_state_user_journey_pilot import click_tab, click_thread, prepare_saved_state, screen_paint
from toad.screens.goal_edit import GoalEdit
from toad.widgets.goal_bar import GoalBar


def seed_goal(comms, text):
    owner = comms.registry.require("beta")
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


if __name__ == "__main__":
    asyncio.run(native_fixture(app_type=InstalledApp, prepare_state=prepare_state,
                              acceptance=acceptance))
