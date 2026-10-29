"""A recorded transcript keeps its selected source through snapshot, refresh and presentation, with no live owner."""

from agent_comms.repo import Checkout
import json
from dataclasses import fields, replace

import pytest

from agent_comms.acp_extension import TranscriptSnapshotUpdate, decode_updates, encode_updates
from agent_comms.coordination_errors import HistoricalSourceChanged, StaleRevision
from agent_comms.order_tools import TranscriptPageRead
from agent_comms.session_file import RegistrySessionLocation
from agent_comms.transcripts import RecordedTranscriptReadIdentity
from agent_comms.threads import Thread
from agent_comms.ui_model.observation import NotPublished
from support.roots import installed_wire
from support.journals import assistant_entry, write_journal
from toad.acp.comms_updates import OwnerSnapshotConsumer
from toad.session_scope import KnownTranscript


@pytest.fixture
def recorded(tmp_path, workspace):

    old, live = installed_wire(tmp_path / "old"), workspace.comms
    native = write_journal(tmp_path / "authored.jsonl", assistant_entry("recorded answer", id="answer-1"))
    old.registry.declare(Thread("reader", frozenset(), Checkout(old.root),
                                created_at=10.0, session_file=RegistrySessionLocation.from_path(str(native), old.root)))
    live.registry.declare(Thread("reader", frozenset(), Checkout(live.root), created_at=20.0))
    source = live.views.attach_history(old.root)
    return live, source, native


async def test_recorded_snapshot_stays_immutable_when_original_grows_and_rejects_stale_source(recorded, workspace):
    live, source, native = recorded

    async with workspace.app() as ui:
        reader = ui.app.coordination_access.transcripts
        update = await reader.snapshot(KnownTranscript(str(live.root), "reader"), historical_source=source.key)
        assert isinstance(update.identity, RecordedTranscriptReadIdentity)
        assert decode_updates(encode_updates(update)) == (update,)
        with native.open("a") as output:
            output.write(json.dumps(assistant_entry("later recorded answer", id="answer-2", parent="answer-1")) + "\n")
        refreshed = await reader.publication(update)
        assert refreshed.identity.historical_source == source.key
        assert refreshed.identity.thread.incarnation == source.provenance.threads["reader"].incarnation
        assert [event.text for event in refreshed.page.events] == ["recorded answer"]
        assert refreshed == update
        with pytest.raises(StaleRevision, match="another recorded source"):
            await reader.publication(replace(refreshed, identity=replace(
                refreshed.identity, source=replace(source, original_root="another-source"))))
        live.bus.history.path.write_text("[]")
        with pytest.raises(HistoricalSourceChanged, match="detached"):
            await reader.publication(refreshed)


def test_recorded_presentation_does_not_acquire_live_owner(recorded):
    live, source, _native = recorded
    presentation = live.views.thread_presentations(("reader",)).read("reader")
    identity = live.transcripts.capture_page_read("reader", historical_source=source.key).identity
    # There is no live agent/controller to acquire: the recorded declaration
    # cannot publish a turn even when delivered to the ordinary snapshot consumer.
    consumer = OwnerSnapshotConsumer(None, "authored", turn_token=1)
    consumer.thread_presentation(replace(presentation, read_identity=identity))
    assert TranscriptSnapshotUpdate.capture(live.transcripts, "reader",
                                            historical_source=source.key).identity == identity


def test_known_transcript_requests_carry_the_page_operation_and_keep_root_at_the_envelope(recorded):
    live, source, _native = recorded
    scope = KnownTranscript(str(live.root), "reader")
    cursor = live.transcripts.capture_page_read("reader", historical_source=source.key).read().after
    snapshot = scope.snapshot_request(before=cursor, historical_source=source.key)
    assert snapshot.root == str(live.root)
    assert snapshot.operation == TranscriptPageRead(
        thread="reader", before=cursor, historical_source=source.key)
    previous = NotPublished()
    update = scope.update_request(previous, after=cursor)
    assert update.root == str(live.root) and update.previous is previous
    assert update.operation == TranscriptPageRead(thread="reader", after=cursor)
    # The shared operation never carries the UI's root, request or publication witness.
    assert not {"root", "request_id", "previous", "identity"} & {f.name for f in fields(TranscriptPageRead)}
