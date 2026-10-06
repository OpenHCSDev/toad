"""Paired source consumers retain the archived witness without live admission."""

import asyncio
import json
from dataclasses import replace

import pytest

from agent_comms.acp_extension import TranscriptSnapshotUpdate, decode_updates, encode_updates
from agent_comms.comms import Comms
from agent_comms.coordination_errors import StaleRevision
from agent_comms.transcripts import RecordedTranscriptReadIdentity
from toad.acp.comms_updates import OwnerSnapshotConsumer
from toad.acp.transcript_reader import DirectTranscriptReadDelivery


@pytest.fixture
def recorded(tmp_path):
    from agent_comms.threads import Thread

    old, live = Comms(tmp_path / "old"), Comms(tmp_path / "live")
    native = tmp_path / "authored.jsonl"
    native.write_text(json.dumps({"type": "message", "message": {
        "role": "assistant", "content": [{"type": "text", "text": "recorded answer"}],
    }}) + "\n")
    old.registry.declare(Thread("reader", frozenset(), str(old.root),
                                created_at=10.0, session_file=str(native)))
    old.messaging.initialize_private_initial_protocol()
    live.registry.declare(Thread("reader", frozenset(), str(live.root), created_at=20.0))
    source = live.views.attach_history(old.root)
    return live, source, native


def test_recorded_snapshot_wire_and_stale_publication_keep_selected_source(recorded):
    live, source, native = recorded

    async def check():
        reader = DirectTranscriptReadDelivery()
        update = await reader.snapshot(str(live.root), "reader", historical_source=source.key)
        assert isinstance(update.identity, RecordedTranscriptReadIdentity)
        assert decode_updates(encode_updates(update)) == (update,)
        with native.open("a") as output:
            output.write(json.dumps({"type": "message", "message": {
                "role": "assistant", "content": [{"type": "text", "text": "later recorded answer"}],
            }}) + "\n")
        refreshed = await reader.publication(update)
        assert refreshed.identity.historical_source == source.key
        assert refreshed.identity.thread.incarnation == source.provenance.threads["reader"].incarnation
        assert [event.text for event in refreshed.page.events] == ["recorded answer", "later recorded answer"]
        assert refreshed.identity != update.identity
        with pytest.raises(StaleRevision, match="another recorded source"):
            await reader.snapshot(str(live.root), "reader", read_identity=refreshed.identity,
                                  historical_source="another-source")
        live.bus.history.path.write_text("[]")
        with pytest.raises(ValueError, match="detached"):
            await reader.publication(refreshed)

    asyncio.run(check())


def test_recorded_presentation_does_not_acquire_live_owner(recorded):
    live, source, _native = recorded
    presentation = live.views.thread_presentation("reader")
    identity = live.transcripts.capture_page_read("reader", historical_source=source.key).identity
    # There is no live agent/controller to acquire: the recorded declaration
    # cannot publish a turn even when delivered to the ordinary snapshot consumer.
    consumer = OwnerSnapshotConsumer(None, "authored", turn_token=1)
    consumer.thread_presentation(replace(presentation, read_identity=identity))
    assert TranscriptSnapshotUpdate.capture(live.transcripts, "reader",
                                            historical_source=source.key).identity == identity
