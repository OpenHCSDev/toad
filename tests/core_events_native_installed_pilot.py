"""Exercise the event migration through existing installed native/ACP/UI owners."""

import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
import time

from l0a_native_installed_pilot import main, response_painted, until
from runtime_fixture import ToadApp
from toad.navigation_target import channel_target, NavigationContext
from toad.widgets.prompt import AgentInfo, QueueSummary
from toad.widgets.comms_menu import ContextMenu
from toad.widgets.transcript_history import TranscriptHistory


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    root = Path(os.environ["L0A_EVIDENCE"])
    start = time.monotonic()
    view = app.selected_session.conversation
    mode = app.selected_mode
    await until(pilot, lambda: view.agent_ready)
    view.prompt.text = "U1_NATIVE_EDITOR_FIRST"
    view.prompt.prompt_text_area.focus()
    await pilot.press("enter")
    await until(pilot, entered.is_set)
    await until(pilot, lambda: comms.registry.require("beta").executing)
    app.save_screenshot(str(root / "native-busy.svg"))

    view.prompt.text = "U1_NATIVE_EDITOR_QUEUED"
    view.prompt.prompt_text_area.focus()
    await pilot.press("enter")
    await until(pilot, lambda: bool(view.queue_projection.items))
    assert "U1_NATIVE_EDITOR_QUEUED" in view.query_one(QueueSummary).render().plain
    queued_id, = [row.input_id for row in view.queue_projection.items]
    app.save_screenshot(str(root / "native-queued.svg"))
    release.set()
    await until(pilot, lambda: len(requests) == 2 and not comms.registry.require("beta").executing, 35)
    await until(pilot, lambda: response_painted(app, view, "NATIVE_RESPONSE_2"), 25)
    await until(pilot, lambda: not view.queue_projection.items and view.turns.managed_id is None)
    assert view.agent_ready
    await until(pilot, lambda: all(h.checkpoint_available for h in view.contents.query(TranscriptHistory)))
    view.window.anchor()
    view.transcript.require_checkpoint()
    await until(pilot, lambda: not view.transcript.dirty and response_painted(app, view, "NATIVE_RESPONSE_2"))
    assert view.contents.query(TranscriptHistory)
    assert view.transcript.displayed_cursor is not None

    view.prompt.text = "U1_PRESERVED_UNSENT_DRAFT"
    editor = view.prompt.prompt_text_area
    document, undo = editor.document, editor.history
    owner = comms.registry.require("beta").process_identity
    assert await pilot.click(view.prompt.query_one(AgentInfo))
    await until(pilot, lambda: view.prompt.model_switcher.search_input.has_focus)
    await pilot.press("down", "enter")
    await until(pilot, lambda: isinstance(app.screen, ContextMenu))
    high = next(item for item in app.screen.query("ContextMenuItem") if item.action == "high")
    await until(pilot, lambda: high in app.screen._compositor.visible_widgets and high.region.width > 0)
    assert await pilot.click(high, offset=(1, 0))
    await until(pilot, lambda: agent.configuration.thinking.current == "high")
    assert comms.registry.require("beta").thinking_level == "high"

    user = comms.messaging.user_identity(str(agent.project_root_path)).name
    await channel_target("#team").open(NavigationContext(app, mode, agent.project_root_path, user))
    await app.selected_session.wait_content_ready()
    channel_mode = app.selected_mode
    assert channel_mode != mode
    assert await pilot.click(f"SessionLabel#{mode}")
    await until(pilot, lambda: app.selected_mode == mode and response_painted(app, view, "NATIVE_RESPONSE_2"))
    assert app.selected_session.conversation is view
    assert view.prompt.text == "U1_PRESERVED_UNSENT_DRAFT"
    assert editor.document is document and editor.history is undo
    assert comms.registry.require("beta").process_identity == owner
    assert len(requests) == 2
    await agent.session.reconnect()
    await until(pilot, agent.session.settled.is_set)
    await until(pilot, lambda: view.agent_ready and response_painted(app, view, "NATIVE_RESPONSE_2"))
    assert agent.configuration.thinking.current == "high"
    assert len(requests) == 2 and not view.queue_projection.items
    app.save_screenshot(str(root / "native-return.svg"))
    (root / "native-events-receipt.json").write_text(json.dumps({
        "result": "PASS", "elapsed_seconds": time.monotonic() - start,
        "native_requests": len(requests), "queued_input_id": queued_id,
        "original_mode": mode, "channel_mode": channel_mode,
        "physical_pilot_enter": True, "saved_response_painted": True,
        "queue_cleared": True, "idle_ready": view.agent_ready,
        "draft_document_undo_preserved": True, "same_owner": True,
        "thinking": agent.configuration.thinking.current,
        "scope": "Installed Toad/Textual/ACP/Pi with two controlled localhost responses; no public input or paid provider",
    }, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance,
                     fixture_stage=os.environ["U1_FIXTURE_ROOT"], provider_request_budget=2))
