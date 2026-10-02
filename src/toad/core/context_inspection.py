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
from agent_comms.selected_source import SessionRevision, SessionObservation
from agent_comms.threads import Thread
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
        return NativeDetail().dispatch_sync(self.segment)


class ContextProjection(MroDispatch):
    """A leaf projection returns display data rather than mutating an event."""
    def consume_handlers_sync(self, value, handlers):
        return next(iter(handlers))(value)


class NativeDetail(ContextProjection):
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
        message = PiMessage.from_wire(self.raw)
        calls = tuple(call for part in message.parts for call in part.tool_calls())
        tool_text = "\n".join(json.dumps(FieldCodec.encode(call), ensure_ascii=False,
                                        indent=2) for call in calls)
        usage = ("Provider usage on this original message:\n" + json.dumps(
            FieldCodec.encode(message.usage), ensure_ascii=False, indent=2)
            if message.usage is not None else "")
        return "\n".join(filter(None, (message.text, tool_text, usage))) or (
            "No public text in this message. Images, opaque content and private reasoning "
            "are not rendered.")


class SegmentNodes(ContextProjection):
    def __init__(self, key):
        self.key = key

    @handles(MeasuredNativeSegment)
    def segment(self, segment):
        return NativeSegmentNode(self.key, segment)

    @handles(NativeMessages)
    def messages(self, segment):
        return NativeMessagesNode(self.key, segment)


@dataclass(frozen=True)
class NativeMessagesNode(NativeSegmentNode):
    page_size: int = 64

    def children(self):
        return (*super().children(),
                *(NativeMessageRange(f"{self.key}/range/{start}", self.segment,
                                     start, min(start + self.page_size, len(self.segment.messages)))
                  for start in range(0, len(self.segment.messages), self.page_size)))


@dataclass(frozen=True)
class NativeMessageRange(ContextNode):
    segment: NativeMessages
    start: int
    stop: int

    @property
    def label(self):
        return f"Messages {self.start + 1}–{self.stop}"

    def children(self):
        return tuple(NativeMessageNode(f"{self.key.rsplit('/range/', 1)[0]}/message/{i}",
                                      self.segment.messages[i])
                     for i in range(self.start, self.stop))

    def detail(self):
        return "Selected active message range; expand to inspect an individual original message."


@dataclass(frozen=True)
class ContextInspection:
    """Original observed objects and selection identity, shared by any frontend."""
    owner: Thread
    manifests: tuple[ContextManifest, ...]
    source: SessionObservation

    @classmethod
    def read(cls, comms, owner):
        thread = comms.registry.require(owner)
        return cls(thread, comms.bus.log.context_manifests(owner, comms.registry),
                   SessionRevision.observe(thread.session_file))

    def current(self, comms):
        thread = comms.registry.require(self.owner.name)
        return (thread == self.owner
                and self.source == SessionRevision.observe(thread.session_file))

    def recorded(self):
        # Later observations of the same original turn supersede only its view.
        turns = {manifest.turn.require_recorded().identity.value: manifest
                 for manifest in self.manifests}
        return tuple(RecordedTurnNode(f"turn/{identity}", manifest)
                     for identity, manifest in reversed(turns.items()))

    async def native(self, comms):
        owner = await asyncio.to_thread(comms.registry.require, self.owner.name)
        if owner.incarnation != self.owner.incarnation:
            raise ValueError("Selected context thread incarnation changed")
        process = owner.require_process()
        connection = RuntimeConnection(comms, owner.name, socket_path(comms.root, process.pid))
        try:
            payload = await connection.request("context")
            return FieldCodec.decode(NativeContextData, payload).require_session_file(
                owner.require_saved_session())
        finally:
            await connection.close()

    @staticmethod
    def active(context: NativeContextData):
        return tuple(SegmentNodes(f"native/{i}/{segment.declared_name}").dispatch_sync(segment)
                     for i, segment in enumerate(context.segments))
