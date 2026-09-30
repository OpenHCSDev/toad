"""Installed retained native/ACP journey through actual goal and owner menu clicks."""
import asyncio
import json
import os
from importlib.resources import files
from pathlib import Path

from acp.schema import TextContentBlock
from agent_comms.acp import CommsClient
from agent_comms.comms import Comms
from agent_comms.goal_actions import OwnerInvocable, PausedGoalAction, SetGoalAction
from agent_comms.goal_attempts import GoalAttemptStore
from agent_comms.input_disposition import InputDispositions
from toad.app import ToadApp
from toad.thread_actions import StartAction, StopAction
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.comms_sidebar import ChannelGroup, CommsRow
from l0a_native_installed_pilot import main as native_fixture, response_painted, until
from runtime_fixture import wait_channel_roster
from saved_state_user_journey_pilot import SavedStateSubscriber, click_tab, submit_editor


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


async def prepare(comms, project, requests, entered, release, hold_next):
    release.set()
    hold_next.clear()
    client = CommsClient(
        comms, runtime_enabled=True,
        private_nk_native_package=Path(os.environ["AC_NATIVE_COPIED_PACKAGE"]),
        private_nk_wire_root_id=os.environ["AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID"],
    )
    subscriber = SavedStateSubscriber()
    client.on_connect(subscriber)
    try:
        await client.load_session(cwd=str(project), session_id="beta")
        for number in (1, 2):
            await client.prompt("beta", [TextContentBlock(
                type="text", text=f"C3_RETAINED_{number}\n" + "Real retained context.\n" * 40,
            )])
            subscriber.require_success()
    finally:
        await client.shutdown()
    private = comms.root / "goal-private"
    private.mkdir(mode=0o700, exist_ok=True)
    store = GoalAttemptStore.initialize(private)
    goal = comms.goals.update_goal(
        "beta", SetGoalAction(text="One explicitly resumed controlled continuation"),
        actor=OwnerInvocable, owner_store=store,
    )
    comms.goals.update_goal("beta", PausedGoalAction(), actor=OwnerInvocable)
    snapshot = comms.registry.snapshot()
    InputDispositions(comms.root / InputDispositions.filename).record(
        "acp:c3-retained-unknown", seq=None, owner="beta",
        admission=snapshot.admission_generations["beta"], target="beta",
        text="Retain this unresolved original; never replay it",
    )
    assert len(requests) == 2
    assert store.snapshot(goal.id).number == 1
    entered.clear()
    release.clear()
    hold_next.set()


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    evidence = Path(os.environ["L0A_EVIDENCE"])
    view = app.selected_session.conversation
    first = app.selected_session.id
    session = Path(comms.registry.require("beta").session_file)
    history = session.read_bytes()
    dispositions = InputDispositions(comms.root / InputDispositions.filename)
    unknown = dispositions.read().lookup("acp:c3-retained-unknown")
    await until(pilot, lambda: view.agent_ready and response_painted(app, view, "NATIVE_RESPONSE_2"))
    await until(pilot, lambda: view.goal_display.snapshot is not None)
    assert view.goal_display.snapshot.state.pause_source.instruction()
    assert len(requests) == 2, "Cold saved attachment must not prompt"
    app.save_screenshot(str(evidence / "saved-paused.svg"))
    assert await pilot.click("#goal-toggle")
    await until(pilot, entered.is_set)
    await until(pilot, lambda: comms.registry.require("beta").executing)
    assert await pilot.click("#goal-toggle")
    await until(pilot, lambda: comms.registry.require("beta").goal.state.protected)
    assert comms.registry.require("beta").executing, "Pause must not cancel this native turn"
    app.save_screenshot(str(evidence / "paused-active-native.svg"))
    release.set()
    hold_next.clear()
    await until(pilot, lambda: not comms.registry.require("beta").executing)
    await until(pilot, lambda: response_painted(app, view, "NATIVE_RESPONSE_3"))
    editor = view.prompt.prompt_text_area
    assert await pilot.click(editor)
    await pilot.press(*list("C3_DRAFT"))
    document, undo = editor.document, editor.history
    sidebar = await wait_channel_roster(app, pilot, "#team")
    row = next(row for row in sidebar.query(CommsRow) if row.target_name == "#team")
    row.scroll_visible(animate=False, immediate=True)
    assert await pilot.click(row)
    await until(pilot, lambda: app.selected_session.id != first)
    await click_tab(app, pilot, first)
    await until(pilot, lambda: response_painted(app, view, "NATIVE_RESPONSE_3"))
    assert view.prompt.text == "C3_DRAFT"
    assert editor.document is document and editor.history is undo
    assert len(requests) == 3
    reopened = Comms(comms.root)
    paused = reopened.registry.require("beta").goal
    assert paused.state.pause_source.instruction()
    assert reopened.goals.goal_history("beta")[-1].after == paused
    assert not (comms.root / "goal_pause_events.json").exists()
    assert dispositions.read().lookup(unknown.key) == unknown
    sidebar = await wait_channel_roster(app, pilot, "#team")
    group = next(group for group in sidebar.query(ChannelGroup) if group.row.target_name == "#team")
    if not group.expanded:
        group.toggle_members()
    await until(pilot, lambda: any(row.target_name == "beta" for row in sidebar.query(CommsRow)))
    member = next(row for row in sidebar.query(CommsRow) if row.target_name == "beta")
    assert await pilot.click(member, button=3)
    await until(pilot, lambda: bool(app.screen.query(ContextMenuItem)))
    assert not any(item.action == StartAction.declared_name for item in app.screen.query(ContextMenuItem))
    stop = next(item for item in app.screen.query(ContextMenuItem) if item.action == StopAction.declared_name)
    assert await pilot.click(stop)
    await until(pilot, lambda: comms.registry.status("beta").stopped)
    await until(pilot, lambda: not comms.registry.require("beta").process_alive)
    await until(pilot, lambda: "beta" not in app.thread_actions.pending)
    sidebar = await wait_channel_roster(app, pilot, "#team")
    member = next(row for row in sidebar.query(CommsRow) if row.target_name == "beta")
    assert await pilot.click(member, button=3)
    await until(pilot, lambda: bool(app.screen.query(ContextMenuItem)))
    start = next(item for item in app.screen.query(ContextMenuItem) if item.action == StartAction.declared_name)
    app.save_screenshot(str(evidence / "stopped-start-menu.svg"))
    assert await pilot.click(start)
    await until(pilot, lambda: comms.registry.require("beta").process_alive)
    await until(pilot, lambda: "beta" not in app.thread_actions.pending)
    await until(pilot, lambda: view.agent_ready)
    assert len(requests) == 3, "Owner restart must not replay an input"
    editor.action_select_all()
    await pilot.press("backspace")
    await submit_editor(pilot, editor, "C3_NEW_INPUT_AFTER_OWNER_START")
    await until(pilot, lambda: response_painted(app, view, "NATIVE_RESPONSE_4"))
    await until(pilot, lambda: not comms.registry.require("beta").executing)
    assert len(requests) == 4
    assert session.read_bytes().startswith(history)
    assert dispositions.read().lookup(unknown.key) == unknown
    app.save_screenshot(str(evidence / "new-input-after-start.svg"))
    receipt = {
        "core": __import__("agent_comms").__file__, "toad": __import__("toad").__file__,
        "provider": "controlled localhost only", "requests": len(requests),
        "physical_goal_pause_resume": True, "pause_did_not_cancel_native": True,
        "cold_pause_source": "original Goal.state", "channel_agent_return_draft_undo": True,
        "physical_stop_start_new_input": True, "retained_history_prefix": True,
        "original_unknown_unchanged": True, "default_activation": False,
    }
    (evidence / "c3-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(native_fixture(
        app_type=InstalledApp, acceptance=acceptance, prepare_state=prepare,
        native_settings={"compaction": {"enabled": False}, "retry": {"enabled": False}},
        provider_request_budget=4, fixture_stage=Path(os.environ["C3_FIXTURE_STAGE"]),
    ))
