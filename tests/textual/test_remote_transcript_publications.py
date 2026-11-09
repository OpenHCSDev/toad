"""A remote page carries publication answers, never filesystem work for the renderer."""

from agent_comms.nominal.field_codec import FieldCodec
from agent_comms.transcript.transcripts import TranscriptPage

from toad.transcript_preparation import PreparedTranscriptPage


def test_remote_page_renders_without_the_server_bus(workspace):
    workspace.thread("source")
    workspace.thread("peer")
    message = workspace.comms.messaging.send("source", "peer", "PHONE_REMOTE_PUBLICATION").message
    page = workspace.comms.transcripts.capture_page_read("source").read()
    remote = FieldCodec.decode(TranscriptPage, FieldCodec.encode(page))
    database = workspace.comms.bus.bus.path
    absent = database.with_suffix(".off-device")
    database.rename(absent)
    try:
        prepared = PreparedTranscriptPage.prepare(remote)
    finally:
        absent.rename(database)
    assert len(prepared.outgoing_coverage) == 1
    reference, = prepared.outgoing_coverage
    assert reference.message == message.reference
    assert reference.scope.root == str(workspace.comms.root)
    assert reference.scope.recipient == workspace.comms.registry.require("source").incarnation
