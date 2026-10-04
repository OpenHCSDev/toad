"""Read-only context references. The SDK owns selection and token estimates."""
from __future__ import annotations

import json
from pathlib import Path
from abc import ABC
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Awaitable, Callable

from agent_comms.field_codec import FieldCodec
from agent_comms.coordinator import Coordination
from agent_comms.mro_dispatch import handles
from toad.core.projection import MroProjection
from agent_comms.native_turn_context import NativeContextData
from agent_comms.pi_payloads import PiMessage
from agent_comms.runtime import RuntimeConnection, socket_path
from agent_comms.selected_source import SessionRevision, SessionObservation
from agent_comms.threads import Thread
from agent_comms.turn_context import (
    ContextManifest, ContextSegment, ContextSourceText, NativeMessages, Provenance,
    SegmentManifest,
)

if TYPE_CHECKING:
    from agent_comms.comms import Comms


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

    async def read(self):
        return await Coordination.run_worker(self.detail)

    async def export(self, destination: Path):
        """Export this original observation; never overwrite a session/source file."""
        detail = await self.read()
        await Coordination.run_worker(partial(self._write_export, destination, detail))

    @staticmethod
    def _write_export(destination, detail):
        with destination.open("x", encoding="utf-8") as output:
            output.write(detail)


@dataclass(frozen=True)
class ReferenceNode(ContextNode):
    source: Provenance
    read_source: Callable[[Provenance], Awaitable[ContextSourceText]]

    @property
    def label(self):
        return f"Source · {self.source.public_description()}"

    def detail(self):
        return self.source.public_description()

    def public_text(self):
        return self.source.public_description()

    async def read(self):
        original = await self.read_source(self.source)
        return f"{original.description}\n\n{original.text}"


@dataclass(frozen=True)
class ManifestNode(ContextNode):
    segment: SegmentManifest
    read_source: Callable[[Provenance], Awaitable[ContextSourceText]]

    @property
    def label(self):
        return self.segment.public_description()

    def children(self):
        return (
            *(ManifestNode(f"{self.key}/contributor/{i}", child, self.read_source)
              for i, child in enumerate(self.segment.contributors)),
            *(ReferenceNode(f"{self.key}/source/{i}", source, self.read_source)
              for i, source in enumerate(self.segment.provenance)),
        )

    def detail(self):
        return (f"{self.segment.kind.public_title()}\nEstimate: {self.segment.tokens:,} tokens\n"
                f"Original bytes: {self.segment.utf8_bytes:,}\n"
                f"Digest: {self.segment.sha256}\n\n"
                "This manifest records the request's sources and measurements, not its text. "
                "Current native base is not evidence of this earlier request's wording.")


@dataclass(frozen=True)
class RecordedTurnNode(ContextNode):
    manifest: ContextManifest
    inspection: ContextInspection

    @property
    def label(self):
        turn = self.manifest.turn.require_recorded()
        return f"Request {turn.occurrence.generation} · {turn.identity.value[:12]}"

    def children(self):
        return tuple(ManifestNode(f"{self.key}/{i}", segment,
                                 partial(self.inspection.recorded_source, self.manifest, i))
                     for i, segment in enumerate(self.manifest.segments))

    def detail(self):
        return (f"Recorded turn · {self.manifest.turn.require_recorded().identity.value}\n"
                f"Counter: {self.manifest.counter}\n\n"
                "Historical request observation, not an additional active context section. "
                "Segment counts are estimates, not provider measurements.")


@dataclass(frozen=True)
class NativeSegmentNode(ContextNode):
    segment: ContextSegment
    read_source: Callable[[Provenance], Awaitable[ContextSourceText]]

    @property
    def label(self):
        return self.segment.public_description()

    def children(self):
        return (
            *(ManifestNode(f"{self.key}/contributor/{i}", child, self.read_source)
              for i, child in enumerate(self.segment.contributor_manifests())),
            *(ReferenceNode(f"{self.key}/source/{i}", source, self.read_source)
              for i, source in enumerate(self.segment.provenance)),
        )

    def detail(self):
        sources = "\n\n".join(
            source.public_description()
            for source in self.segment.provenance
        )
        return f"{self.label}\n\n{self.public_text()}\n\nSources:\n{sources}"

    def public_text(self):
        return self.segment.public_text()


@dataclass(frozen=True)
class NativeMessageNode(NativeSegmentNode):
    message: PiMessage
    position: int

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
        return f"{super().detail()}\n\n{usage}" if usage else super().detail()


class SegmentNodes(MroProjection):
    def __init__(self, key, read_source):
        self.key, self.read_source = key, read_source

    @handles(ContextSegment)
    def segment(self, segment):
        return NativeSegmentNode(self.key, segment, self.read_source)

    @handles(NativeMessages)
    def messages(self, segment):
        return NativeMessagesNode(self.key, segment, self.read_source)


@dataclass(frozen=True)
class NativeMessagesNode(NativeSegmentNode):
    page_size: int = 64

    def public_text(self):
        # This navigation container delegates searching to its original
        # message children rather than concatenating the same history twice.
        return ""

    def detail(self):
        return f"{self.label}\nExpand a message range to read each original public message."

    def children(self):
        return (*super().children(),
                *(NativeMessageRange(f"{self.key}/range/{start}", self.segment, self.read_source,
                                     start, min(start + self.page_size, len(self.segment.messages)))
                  for start in range(0, len(self.segment.messages), self.page_size)))


@dataclass(frozen=True)
class NativeMessageRange(ContextNode):
    segment: NativeMessages
    read_source: Callable[[Provenance], Awaitable[ContextSourceText]]
    start: int
    stop: int

    @property
    def label(self):
        return f"Messages {self.start + 1}–{self.stop}"

    def children(self):
        return tuple(NativeMessageNode(f"{self.key}/message/{i}", segment=self.segment,
                                      read_source=self.read_source,
                                      message=PiMessage.from_wire(self.segment.messages[i]), position=i)
                     for i in range(self.start, self.stop))

    def detail(self):
        return "Current native message range; expand to read the original public text."


@dataclass(frozen=True)
class ContextInspection:
    """Original observed objects and selection identity, shared by any frontend."""
    owner: Thread
    manifests: tuple[ContextManifest, ...]
    source: SessionObservation
    service: Comms

    @classmethod
    def read(cls, comms, owner):
        thread = comms.registry.require(owner)
        return cls(thread, comms.bus.log.context_manifests(owner, comms.registry),
                   SessionRevision.observe(thread.session_file), comms)

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
        return tuple(RecordedTurnNode(f"turn/{identity}", manifest, self)
                     for identity, manifest in reversed(turns.items()))

    def find(self, native, query: str, *, limit=100):
        """Bound result widgets, while searching the original available public text."""
        from itertools import islice

        normalized = query.casefold()
        nodes = (*self.contributors(native), *self.active(native)) if native is not None else ()
        return tuple(islice((match for node in nodes for match in node.find(normalized)), limit))

    async def _request(self, action, **parameters):
        owner = await Coordination.run_worker(partial(self.service.registry.require, self.owner.name))
        if owner.incarnation != self.owner.incarnation:
            raise ValueError("Selected context thread incarnation changed")
        process = owner.require_process()
        connection = RuntimeConnection(self.service, owner.name, socket_path(self.service.root, process.pid))
        try:
            return await connection.request(action, **parameters)
        finally:
            await connection.close()

    async def native(self):
        payload = await self._request("context")
        context = await Coordination.run_worker(partial(FieldCodec.decode, NativeContextData, payload))
        return context.require_session_file(self.owner.require_saved_session())

    async def current_source(self, context, position, source):
        payload = await self._request("context_source",
            observation=FieldCodec.encode(context.observation()), segment=position,
            source=FieldCodec.encode(source))
        return FieldCodec.decode(ContextSourceText, payload)

    async def recorded_source(self, manifest, position, source):
        payload = await self._request("context_reference",
            turn=FieldCodec.encode(manifest.turn), request_id=manifest.require_request_id(),
            segment=position, source=FieldCodec.encode(source))
        return FieldCodec.decode(ContextSourceText, payload)

    def active(self, context: NativeContextData):
        return tuple(SegmentNodes(f"native/{context.identity.session_id}/{i}/{segment.declared_name}/{segment.sha256}",
                                 partial(self.current_source, context, i)).dispatch_sync(segment)
                     for i, segment in enumerate(context.segments))

    def contributors(self, context: NativeContextData):
        return tuple(SegmentNodes(f"core/{context.identity.session_id}/{i}/{segment.declared_name}",
                     partial(self.current_source, context, len(context.segments) + i)).dispatch_sync(segment)
                     for i, segment in enumerate(context.contributors))
