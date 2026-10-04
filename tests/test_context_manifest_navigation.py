"""Current contributor and recorded-child navigation retain decoded members."""

import hashlib
from functools import partial

from agent_comms.comms import Comms
from agent_comms.field_codec import FieldCodec
from agent_comms.thread_identity import TurnId, TurnIdentity
from agent_comms.threads import Thread
from agent_comms.turn_context import (
    ContextManifest,
    ContextSegment,
    OwnerProvenance,
    RecordedContextTurn,
    SystemLayerSegment,
    UserInputSegment,
)
from toad.core.context_inspection import ContextInspection, ManifestNode, NativeSegmentNode


def test_decoded_current_contributor_and_recorded_child_labels(tmp_path):
    service = Comms(tmp_path / "wire")
    service.messaging.initialize_private_initial_protocol()
    owner = service.registry.declare(Thread("annotation-owner", frozenset(), str(tmp_path)))
    source = OwnerProvenance(owner.incarnation, "original-fixture-annotation")
    text = "Public contributor annotation"
    contribution = UserInputSegment(provenance=(source,), content=text).manifest(7)
    original = SystemLayerSegment(
        provenance=(source,), content=text, tokens=7,
        sha256=hashlib.sha256(text.encode()).hexdigest(), utf8_bytes=len(text.encode()),
        contributors=(contribution,),
    )
    current = FieldCodec.decode(ContextSegment, FieldCodec.encode(original))
    turn = RecordedContextTurn(TurnId("annotation-only"), TurnIdentity(owner.incarnation, 1))
    manifest = ContextManifest(owner.incarnation, turn, (original.measured_manifest(),),
                               "fixture.estimate")
    service.bus.log.record_context(manifest)
    inspection = ContextInspection.read(service, owner.name)
    captured = inspection.manifests[0]
    read_reference = partial(inspection.recorded_source, captured, 0)
    current_child = NativeSegmentNode("current", current, read_reference).children()[0]
    recorded_parent = inspection.recorded()[0].children()[0]
    recorded_child = recorded_parent.children()[0]
    assert service.bus.log.total_messages() == 0
    assert isinstance(current_child, ManifestNode) and isinstance(recorded_child, ManifestNode)
    assert current_child.segment.kind is recorded_child.segment.kind is UserInputSegment
    assert current_child.label == recorded_child.label == "User Input · 7 estimated tokens"
    for node in (current_child, recorded_child):
        detail = node.detail()
        assert detail.startswith("User Input\nEstimate: 7 tokens\n")
        assert contribution.sha256 in detail and "<class" not in detail
    assert recorded_parent.segment.kind is SystemLayerSegment
    assert recorded_parent.label == "System Layer · 7 estimated tokens"
