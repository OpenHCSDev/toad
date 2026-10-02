"""Read-only context references. The SDK owns selection and token estimates."""
from __future__ import annotations

import asyncio
import json
from abc import ABC
from dataclasses import dataclass

from agent_comms.field_codec import FieldCodec
from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.native_turn_context import NativeContextData
from agent_comms.pi_payloads import PiMessage
from agent_comms.runtime import RuntimeConnection, socket_path
from agent_comms.turn_context import (
    ContextManifest, MeasuredNativeSegment, NativeMessages, Provenance,
    SegmentManifest, SystemLayerSegment, ToolCatalogSegment,
)


@dataclass(frozen=True)
class ContextNode(ABC):
    """Navigation coordinate and original reference, never context authority."""
    key: str

    @property
    def label(self) -> str:
        return "Context"

    def children(self) -> tuple[ContextNode, ...]:
        return ()

    def detail(self) -> str:
        return "No text recorded for this observation."


@dataclass(frozen=True)
class ReferenceNode(ContextNode):
    source: Provenance

    @property
    def label(self):
        return f"Reference · {self.source.declared_name}"

    def detail(self):
        return "Reference only; not read by browsing.\n" + json.dumps(
            FieldCodec.encode(self.source), ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class ManifestNode(ContextNode):
    segment: SegmentManifest

    @property
    def label(self):
        return f"{self.segment.kind} · ~{self.segment.tokens:,} tokens"

    def children(self):
        return (
            *(ManifestNode(f"{self.key}/contributor/{i}", child)
              for i, child in enumerate(self.segment.contributors)),
            *(ReferenceNode(f"{self.key}/source/{i}", source)
              for i, source in enumerate(self.segment.provenance)),
        )

    def detail(self):
        return (f"{self.segment.kind}\nEstimate: {self.segment.tokens:,} tokens\n"
                f"Original bytes: {self.segment.utf8_bytes:,}\n"
                f"Digest: {self.segment.sha256}\n\n"
                "This recorded manifest contains no text. Its references are not dereferenced.")


@dataclass(frozen=True)
class RecordedTurnNode(ContextNode):
    manifest: ContextManifest

    @property
    def label(self):
        turn = self.manifest.turn.require_recorded()
        return f"Turn {turn.occurrence.generation} · {turn.identity.value[:12]}"

    def children(self):
        return tuple(ManifestNode(f"{self.key}/{i}", segment)
                     for i, segment in enumerate(self.manifest.segments))

    def detail(self):
        return (f"Recorded turn · {self.manifest.turn.require_recorded().identity.value}\n"
                f"Counter: {self.manifest.counter}\n\n"
                "Historical request observation, not an additional active context section. "
                "Segment counts are estimates, not provider measurements.")


@dataclass(frozen=True)
class NativeSegmentNode(ContextNode):
    segment: MeasuredNativeSegment

    @property
    def label(self):
        return f"{self.segment.declared_name} · ~{self.segment.tokens:,} tokens"

    def children(self):
        return (
            *(ManifestNode(f"{self.key}/contributor/{i}", child)
              for i, child in enumerate(self.segment.contributors)),
            *(ReferenceNode(f"{self.key}/source/{i}", source)
              for i, source in enumerate(self.segment.provenance)),
        )

    def detail(self):
        return NativeDetail().dispatch(self.segment)


class NativeDetail(MroDispatch):
    """Use existing SDK segment and content owners; omit private reasoning."""
    @handles(SystemLayerSegment)
    def system(self, segment):
        return segment.content

    @handles(NativeMessages)
    def messages(self, segment):
        return "Expand this segment to inspect an individual message."

    @handles(ToolCatalogSegment)
    def tools(self, segment):
        return json.dumps(segment.tools, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class NativeMessageNode(ContextNode):
    raw: dict

    @property
    def label(self):
        return f"Message {int(self.key.rsplit('/', 1)[1]) + 1}"

    def detail(self):
        message = FieldCodec.decode(PiMessage, self.raw)
        calls = tuple(call for part in message.parts for call in part.tool_calls())
        tool_text = "\n".join(json.dumps(FieldCodec.encode(call), ensure_ascii=False,
                                        indent=2) for call in calls)
        return "\n".join(filter(None, (message.text, tool_text))) or (
            "No public text in this message. Images, opaque content and private reasoning "
            "are not rendered.")


class SegmentNodes(MroDispatch):
    @handles(MeasuredNativeSegment)
    def segment(self, segment, key):
        return NativeSegmentNode(key, segment)

    @handles(NativeMessages)
    def messages(self, segment, key):
        return NativeMessagesNode(key, segment)


@dataclass(frozen=True)
class NativeMessagesNode(NativeSegmentNode):
    def children(self):
        # Message bodies are decoded only when this branch is expanded/selected.
        return (*super().children(),
                *(NativeMessageNode(f"{self.key}/message/{i}", message)
                  for i, message in enumerate(self.segment.messages)))


@dataclass(frozen=True)
class ContextInspection:
    """Original observed objects and selection identity, shared by any frontend."""
    owner: str
    manifests: tuple[ContextManifest, ...]

    @classmethod
    def read(cls, comms, owner):
        return cls(owner, comms.bus.log.context_manifests(owner, comms.registry))

    def recorded(self):
        # Later observations of the same original turn supersede only its view.
        turns = {manifest.turn.require_recorded().identity.value: manifest
                 for manifest in self.manifests}
        return tuple(RecordedTurnNode(f"turn/{identity}", manifest)
                     for identity, manifest in reversed(turns.items()))

    async def native(self, comms):
        owner = await asyncio.to_thread(comms.registry.require, self.owner)
        process = owner.require_process()
        connection = RuntimeConnection(comms, owner.name, socket_path(comms.root, process.pid))
        try:
            payload = await connection.request("context", prepare=False)
            return FieldCodec.decode(NativeContextData, payload).require_session_file(
                owner.require_saved_session())
        finally:
            await connection.close()

    @staticmethod
    def active(context: NativeContextData):
        projection = SegmentNodes()
        return tuple(projection.dispatch(segment, f"native/{i}/{segment.declared_name}")
                     for i, segment in enumerate(context.segments))
