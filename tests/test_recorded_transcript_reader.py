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


@pytest.mark.parametrize("retirement", (None, "selection", "body", "screen", "detached"))
def test_historical_notification_publication_preserves_selected_source_and_lifetime(
    tmp_path, monkeypatch, retirement,
):
    """Source callback boundary only; no mounted App/rendering qualification."""
    from types import SimpleNamespace

    from agent_comms.historical_views import HistoricalThread, HistorySource
    from agent_comms.threads import Thread
    from toad.screens.historical_sessions import HistoricalSessions
    from toad.widgets.wire_message_handling import WireMessageHandling

    old, live = Comms(tmp_path / "old"), Comms(tmp_path / "live")
    old.registry.declare(Thread("sender", frozenset(), str(tmp_path), created_at=10.0))
    old.registry.declare(Thread("agent", frozenset(), str(tmp_path), created_at=12.0))
    live.registry.declare(Thread("agent", frozenset(), str(tmp_path), created_at=212.0))
    old.messaging.initialize_private_initial_protocol()
    messages = (old.messaging.send_initial_cohort("sender", "agent", "historical notification"),)
    source = live.views.attach_history(old.root)
    item = HistoricalThread(source, source.provenance.require("agent"))
    published, errors, selected = [], [], []
    body = SimpleNamespace(
        is_attached=True, handling_references=(messages[0].reference,),
        show_notifications=published.append, show_notification_error=errors.append,
    )
    owner = SimpleNamespace(comms=live, _selection_generation=1, is_attached=True,
                            query_one=lambda *_: object())
    monkeypatch.setattr(WireMessageHandling, "within", lambda *_: (body,))
    original = HistorySource.notification_references

    def read(captured, archive, references):
        selected.append(captured.key)
        if retirement == "detached":
            live.bus.history.path.write_text("[]")
        result = original(captured, archive, references)
        if retirement == "selection":
            owner._selection_generation += 1
        elif retirement == "body":
            body.is_attached = False
        elif retirement == "screen":
            owner.is_attached = False
        return result

    monkeypatch.setattr(HistorySource, "notification_references", read)
    asyncio.run(HistoricalSessions.publish_handling(owner, item, 1))
    assert selected == [source.key]
    if retirement is None:
        assert not errors and len(published) == 1
        notification, = published[0][messages[0].seq, messages[0].message_id]
        assert notification.state == "Pending" and not notification.busy
    elif retirement == "detached":
        assert not published and len(errors) == 1
        assert "detached" in str(errors[0])
    else:
        assert not published and not errors
