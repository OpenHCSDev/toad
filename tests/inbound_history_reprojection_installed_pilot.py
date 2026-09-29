"""Continuous real UI/ACP/native journey: source ownership survives retirement."""
import asyncio
import json
import sys
from pathlib import Path
from agent_comms.threads import Thread

from l0a_native_installed_pilot import main, until
from receiver_inbound_installed_pilot import paint
from toad.widgets.incoming_message import AssignedIncomingMessage, IncomingMessage
from toad.widgets.observed_thread_activity import ObservedThreadActivity
from toad.widgets.transcript_history import TranscriptHistory
from toad.transcript_preparation import incoming_sequences


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    comms.registry.declare(Thread("sender", frozenset({"team"}), str(app.project_dir)))
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "agent_comms.cli", "send", "--from", "sender",
        "--to", "#team", "--body", "@beta RECEIVER_NATIVE_INBOUND_PROOF",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, (stdout, stderr)
    message = comms.bus.log.message_by_id(json.loads(stdout)["id"])
    sequence = message.seq
    await until(pilot, entered.is_set)
    await until(pilot, lambda: any(item.sequence == sequence for item in view.query(IncomingMessage)))
    release.set()
    await until(pilot, lambda: not comms.registry.require("beta").executing)
    print("REAL_AGENT_CHANNEL_MESSAGE_AND_NATIVE_RECEIPT", flush=True)
    await until(pilot, lambda: view.turns.managed_id is None)
    view.window.anchor()
    view.transcript.require_checkpoint()
    await until(pilot, lambda: not view.transcript.dirty)
    await until(pilot, lambda: bool(view.contents.query(TranscriptHistory)))
    assert sequence in incoming_sequences((await agent.get_transcript_page()).events)
    assert not view.contents.query(AssignedIncomingMessage)
    observed = view.query_one(ObservedThreadActivity)

    # A real subsequent native turn changes the observed owner presentation.
    # Its poll reprojects the old assignment while the same chat remains open.
    view.prompt.text = "UNRELATED_NEW_NATIVE_TURN"
    view.prompt.prompt_text_area.focus()
    await pilot.press("enter")
    await until(pilot, lambda: len(requests) == 2)
    await until(pilot, lambda: not comms.registry.require("beta").executing)
    observed.refresh_observation()
    await pilot.pause(.3)
    blocks = [item for item in view.contents.query(IncomingMessage) if item.sequence == sequence]
    assert len(blocks) == 1, [(type(item).__name__, item.sequence) for item in blocks]
    assert not view.contents.query(AssignedIncomingMessage), "Old receipt returned to live tail"
    assert "RECEIVER_NATIVE_INBOUND_PROOF" in paint(app)
    print("SAME_OPEN_VIEW_NATIVE_TURN_AND_ASSIGNMENT_POLL_NO_REPLAY", flush=True)

    # Reattach the real ACP process to the saved owner, without sending an input.
    before = len(requests)
    await agent.session.reconnect()
    await until(pilot, agent.session.settled.is_set)
    assert agent.session.connected
    observed.refresh_observation()
    await pilot.pause(.3)
    assert sum(item.sequence == sequence for item in view.contents.query(IncomingMessage)) == 1
    assert len(requests) == before
    assert not view.contents.query(AssignedIncomingMessage)
    assert app._exception is None
    print("REAL_ACP_RECONNECT_RETAINED_SOURCE_AND_ONE_WIRE_IDENTITY", flush=True)


if __name__ == "__main__":
    asyncio.run(main(acceptance=acceptance, provider_request_budget=2))
