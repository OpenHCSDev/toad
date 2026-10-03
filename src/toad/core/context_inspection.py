"""Read-only context references. The SDK owns selection and token estimates."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from abc import ABC
from dataclasses import dataclass

from agent_comms.field_codec import FieldCodec
from agent_comms.mro_dispatch import handles
from toad.core.projection import MroProjection
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

    def public_text(self) -> str:
        """Only original public content is searchable, never private reasoning."""
        return ""

    def find(self, query: str):
        """Walk original references on demand; do not build a second text index."""
        if query in self.public_text().casefold():
            yield self
        for child in self.children():
            yield from child.find(query)

    def export(self, destination: Path):
        """Export this original observation; never overwrite a session/source file."""
        detail = self.detail()
        with destination.open("x", encoding="utf-8") as output:
            output.write(detail)


@dataclass(frozen=True)
class ReferenceNode(ContextNode):
    source: Provenance

    @property
    def label(self):
        return f"Source · {self.source.declared_name.replace('_', ' ')}"

    def detail(self):
        return "Original source reference; historical text is not inferred from today's file.\n" + json.dumps(
            FieldCodec.encode(self.source), ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class ManifestNode(ContextNode):
    segment: SegmentManifest

    @property
    def label(self):
        return f"{self.segment.kind.replace('_', ' ')} · ~{self.segment.tokens:,} tokens"

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
                "This manifest records the request's sources and measurements, not its text. "
                "Current native base is not evidence of this earlier request's wording.")


@dataclass(frozen=True)
class RecordedTurnNode(ContextNode):
    manifest: ContextManifest

    @property
    def label(self):
        turn = self.manifest.turn.require_recorded()
        return f"Request {turn.occurrence.generation} · {turn.identity.value[:12]}"

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
        return f"{self.segment.declared_name.replace('_', ' ')} · ~{self.segment.tokens:,} tokens"

    def children(self):
        return (
            *(ManifestNode(f"{self.key}/contributor/{i}", child)
              for i, child in enumerate(self.segment.contributors)),
            *(ReferenceNode(f"{self.key}/source/{i}", source)
              for i, source in enumerate(self.segment.provenance)),
        )

    def detail(self):
        return f"{self.label}\n\n{self.public_text()}"

    def public_text(self):
        return NativeDetail().dispatch_sync(self.segment)


class NativeDetail(MroProjection):
    """Use existing SDK segment and content owners; omit private reasoning."""
    @handles(SystemLayerSegment)
    def system(self, segment):
        return segment.content

    @handles(NativeMessages)
    def messages(self, segment):
        return ""

    @handles(ToolCatalogSegment)
    def tools(self, segment):
        return json.dumps(segment.tools, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class NativeMessageNode(ContextNode):
    message: PiMessage
    position: int
    segment: NativeMessages

    def children(self):
        return tuple(ReferenceNode(f"{self.key}/source/{i}", source)
                     for i, source in enumerate(self.segment.provenance))

    @property
    def label(self):
        text = " ".join(self.message.text[:120].split())
        return (f"{self.segment.declared_name.replace('_', ' ')} · "
                f"{self.message.declared_name} {self.position + 1} · {text or 'no public text'}")

    def public_text(self):
        message = self.message
        calls = tuple(call for part in message.parts for call in part.tool_calls())
        tool_text = "\n".join(json.dumps(FieldCodec.encode(call), ensure_ascii=False,
                                        indent=2) for call in calls)
        return "\n".join(filter(None, (message.text, tool_text)))

    def detail(self):
        message = self.message
        usage = ("Provider usage on this original message:\n" + json.dumps(
            FieldCodec.encode(message.usage), ensure_ascii=False, indent=2)
            if message.usage is not None else "")
        content = self.public_text() or (
            "No public text in this message. Images, opaque content and private reasoning "
            "are not rendered.")
        return f"{self.label}\nSegment: {self.segment.declared_name}\n\n{content}\n\n{usage}"


class SegmentNodes(MroProjection):
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

    def detail(self):
        return f"{self.label}\nExpand a message range to read each original public message."

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
        return tuple(NativeMessageNode(f"{self.key}/message/{i}",
                                      PiMessage.from_wire(self.segment.messages[i]), i, self.segment)
                     for i in range(self.start, self.stop))

    def detail(self):
        return "Current native message range; expand to read the original public text."


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

    def same_native_source(self, other: ContextInspection):
        """Compare original SDK source/launch facts, not roster presentation."""
        return (self.source == other.source
                and self.owner.publication_identity == other.owner.publication_identity
                and self.owner.model == other.owner.model
                and self.owner.thinking_level == other.owner.thinking_level)

    def recorded(self):
        # Later observations of the same original turn supersede only its view.
        turns = {manifest.turn.require_recorded().identity.value: manifest
                 for manifest in self.manifests}
        return tuple(RecordedTurnNode(f"turn/{identity}", manifest)
                     for identity, manifest in reversed(turns.items()))

    def find(self, native, query: str, *, limit=100):
        """Bound result widgets, while searching the original available public text."""
        from itertools import islice

        normalized = query.casefold()
        nodes = self.active(native) if native is not None else ()
        return tuple(islice((match for node in nodes for match in node.find(normalized)), limit))

    async def native(self, comms):
        owner = await asyncio.to_thread(comms.registry.require, self.owner.name)
        if owner.incarnation != self.owner.incarnation:
            raise ValueError("Selected context thread incarnation changed")
        process = owner.require_process()
        connection = RuntimeConnection(comms, owner.name, socket_path(comms.root, process.pid))
        try:
            payload = await connection.request("context")
            context = await asyncio.to_thread(FieldCodec.decode, NativeContextData, payload)
            return context.require_session_file(owner.require_saved_session())
        finally:
            await connection.close()

    @staticmethod
    def active(context: NativeContextData):
        return tuple(SegmentNodes(f"native/{context.identity.session_id}/{i}/{segment.declared_name}/{segment.sha256}").dispatch_sync(segment)
                     for i, segment in enumerate(context.segments))
