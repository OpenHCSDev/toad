"""Installed ACP read attachment with distinct admission and process domains.

Reuse the actual owner/App/transport fixture. No input or provider call occurs.
The completed native send/rename journey remains its separate accepted receipt.
"""

import asyncio
import json
import os
from pathlib import Path

from agent_comms.thread_identity import AdmissionIdentity, OwnerIdentity
from l0a_native_installed_pilot import main, until
from submission_native_installed_pilot import InstalledApp


async def prepare_state(comms, project, requests, entered, release, hold_next):
    # Real revocation and presence transactions advance the separate counters.
    # The new isolated registration has no process, original input or goal.
    comms.registry.unregister("beta")
    comms.registry.unregister("beta")
    comms.registry.heartbeat("beta")


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    await until(pilot, lambda: view.agent_ready)
    snapshot = comms.registry.snapshot()
    owner = snapshot.require_active("beta")
    scope = agent.queue_attachment.scope
    assert isinstance(scope.admission, AdmissionIdentity)
    assert scope.admission == snapshot.admission_identity("beta")
    assert scope.session_id == agent.session_id == "beta"
    assert scope.owner_pid == owner.require_process().pid
    original_load = agent.session.load_admission
    assert isinstance(original_load.binding.owner, OwnerIdentity)
    assert original_load.binding.owner == snapshot.owner_identity("beta")
    assert original_load.binding.process == owner.require_process()
    assert scope.admission.admission_generation != original_load.binding.owner.generation
    assert not original_load.superseded_by(snapshot.owner_binding("beta"))
    assert agent.queue_attachment.projection.status == "available"
    assert not agent.queue_attachment.projection.items
    assert agent.queue_attachment.accepts_request(scope)
    assert not view.turns.owner.busy
    assert await agent.get_goal_snapshot() == (None, None)
    editor = view.prompt.prompt_text_area
    editor.focus()
    await pilot.press("d", "r", "a", "f", "t")
    assert editor.text == "draft"
    assert not requests, "Read attachment or editor input initiated a provider request"
    log = agent.presentation.log_path.read_text()
    assert "session/prompt" not in log
    assert "'admission_generation':" in log or '"admission_generation":' in log
    root = Path(os.environ["L0A_EVIDENCE"])
    (root / "receipt.json").write_text(json.dumps({
        "sessionId": scope.session_id,
        "admissionGeneration": scope.admission.admission_generation,
        "registryOwnerGeneration": original_load.binding.owner.generation,
        "originalProcessWitness": original_load.binding.process == owner.require_process(),
        "queueAvailable": agent.queue_attachment.projection.status == "available",
        "draft": editor.text,
        "providerCalls": len(requests),
    }, indent=2))
    (root / "attachment.svg").write_text(app.export_screenshot())
    print("PASS installed ACP/owner/Toad admission attachment; distinct counters, original process witness, ready queue and editable draft; zero prompts/provider calls", flush=True)


if __name__ == "__main__":
    asyncio.run(main(app_type=InstalledApp, prepare_state=prepare_state,
                    acceptance=acceptance, provider_request_budget=0))
