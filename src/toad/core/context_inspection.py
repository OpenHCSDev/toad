"""Read-only context references. The SDK owns selection and token estimates."""
from __future__ import annotations

import json
from pathlib import Path
from abc import ABC
from dataclasses import dataclass, field, replace
from functools import partial
from typing import TYPE_CHECKING, Awaitable, Callable

from agent_comms.field_codec import FieldCodec
from agent_comms.declared_family import DeclaredFamily
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

    def _find_public(self, query):
        if query in self.public_text().casefold():
            yield self
        for child in self.children():
            yield from child._find_public(query)

    async def find(self, query: str, *, limit=100):
        """Search one observed tree in one worker, without a second text index."""
        from itertools import islice

        def read():
            return tuple(islice(self._find_public(query), limit))

        for match in await Coordination.run_worker(read):
            yield match

    @staticmethod
    def search_roots(current_roots):
        return current_roots()

    def search_description(self):
        return "Current public context"

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

    def search_roots(self, current_roots):
        return (self,)

    def search_description(self):
        return self.label

    async def find(self, query, *, limit=100):
        original = await self.read_source(self.source)
        if query in original.text.casefold() or query in original.description.casefold():
            yield self


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
        return tuple(RecordedSegmentNode(f"{self.key}/{i}", self.manifest,
                                         self.inspection, i)
                     for i in range(len(self.manifest.segments)))

    def search_roots(self, current_roots):
        return (self,)

    def search_description(self):
        return self.label

    def detail(self):
        return (f"Recorded turn · {self.manifest.turn.require_recorded().identity.value}\n"
                f"Counter: {self.manifest.counter}\n\n"
                "Historical request observation, not an additional active context section. "
                "Segment counts are estimates, not provider measurements.")

    async def find(self, query, *, limit=100):
        count = 0
        for child in self.children():
            async for match in child.find(query, limit=limit - count):
                yield match
                count += 1
                if count == limit:
                    return


@dataclass(frozen=True)
class RecordedSegmentNode(RecordedTurnNode):
    """An original request and navigation coordinate borrow its authenticated reader."""
    position: int
    contributors: tuple[int, ...] = ()

    @property
    def segment(self):
        return self.manifest.selected_segment(self.position, self.contributors)

    @property
    def label(self):
        return self.segment.public_description()

    def children(self):
        segment = self.segment
        return (
            *(RecordedSegmentNode(f"{self.key}/contributor/{i}", self.manifest,
                                  self.inspection, self.position, (*self.contributors, i))
              for i in range(len(segment.contributors))),
            *(ReferenceNode(f"{self.key}/source/{i}", source,
                            partial(self.inspection.recorded_source,
                                    self.manifest, self.position))
              for i, source in enumerate(segment.provenance)),
        )

    async def source_text(self):
        return await self.inspection.recorded_segment(
            self.manifest, self.position, self.contributors)

    async def read(self):
        original = await self.source_text()
        return f"{original.description}\n\n{original.text}"

    async def find(self, query, *, limit=100):
        # One complete selected value includes its annotation children. Search
        # that value once; opening a child still uses that exact child's path.
        original = await self.source_text()
        if query in original.text.casefold() or query in original.description.casefold():
            yield self

    def search_description(self):
        return f"{super().search_description()} · {self.manifest.turn.require_recorded().identity.value[:12]}"


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

    def changed_since(self, previous: ContextInspection) -> bool:
        """Whether the original recorded request observations changed."""
        return self.manifests != previous.manifests

    async def find(self, roots: tuple[ContextNode, ...], query: str, *, limit=100):
        """Bound result widgets while reading the selected original public sources."""
        normalized = query.casefold()
        matches = []
        for node in roots:
            async for match in node.find(normalized, limit=limit - len(matches)):
                matches.append(match)
                if len(matches) == limit:
                    return tuple(matches)
        return tuple(matches)

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

    async def recorded_segment(self, manifest, position, contributors=()):
        payload = await self._request("context_recorded_segment",
            turn=FieldCodec.encode(manifest.turn), request_id=manifest.require_request_id(),
            segment=position, contributors=contributors)
        return FieldCodec.decode(ContextSourceText, payload)

    def active(self, context: NativeContextData):
        return tuple(SegmentNodes(f"native/{context.identity.session_id}/{i}/{segment.declared_name}/{segment.sha256}",
                                 partial(self.current_source, context, i)).dispatch_sync(segment)
                     for i, segment in enumerate(context.segments))

    def contributors(self, context: NativeContextData):
        return tuple(SegmentNodes(f"core/{context.identity.session_id}/{i}/{segment.declared_name}",
                     partial(self.current_source, context, len(context.segments) + i)).dispatch_sync(segment)
                     for i, segment in enumerate(context.contributors))


class InspectionState(DeclaredFamily, affix="Inspection"):
    """One inspection lifetime; Textual owns workers and Tree resources separately."""

    name = ""
    root = None

    @classmethod
    def for_owner(cls, name: str, root: str | None) -> InspectionState:
        # Decode the original optional managed route once, at attachment.
        return ReadingOwnerInspection(name, root) if name and root is not None else DetachedInspection()

    def bound_to(self, name, root) -> bool:
        return (self.name, self.root) == (name, root)

    def observed_at(self, revision) -> bool:
        return True

    def observe(self, revision) -> InspectionState:
        return self

    async def acquire(self, service, revision) -> InspectionState:
        if str(service.root.resolve()) != self.root:
            raise ValueError("Selected context belongs to another wire root")
        inspection = await Coordination.run_worker(partial(ContextInspection.read, service, self.name))
        return HoldingInspection(inspection, revision)

    def receive_inspection(self, acquired) -> InspectionState:
        return acquired

    def inspection_differs(self, inspection) -> bool:
        return True

    def needs_native(self, inspection, force) -> bool:
        return True

    def same_source(self, inspection) -> bool:
        return False

    def present(self, consumer) -> None:
        """A detached or unacquired owner has no inspection to present."""

    async def refresh_contributors(self, consumer) -> None:
        """Only an acquired native preview owns current contributor refresh."""

    def with_contributors(self, expected, native) -> InspectionState:
        return self

    def with_native(self, inspection, native) -> InspectionState:
        return self

    def native_failed(self, inspection, error) -> InspectionState:
        return self

    def prepare_native(self, consumer) -> None:
        """An owner without an inspection cannot admit native context work."""

    def search_current(self, captured) -> bool:
        return False

    def contains_native(self, matches) -> bool:
        """Ask the acquired native resource; unread states own no such resource.""""
        return False

    @property
    def status(self):
        return "No managed thread context available"


class DetachedInspection(InspectionState):
    async def acquire(self, service, revision) -> InspectionState:
        return self


@dataclass(frozen=True)
class ReadingOwnerInspection(InspectionState):
    name: str = field()
    root: str = field()

    def observed_at(self, revision) -> bool:
        return False

    def observe(self, revision) -> InspectionState:
        return ObservedOwnerInspection(self.name, self.root, revision)


@dataclass(frozen=True)
class ObservedOwnerInspection(ReadingOwnerInspection):
    revision: int

    def observed_at(self, revision) -> bool:
        return self.revision == revision


@dataclass(frozen=True)
class HoldingInspection(InspectionState):
    inspection: ContextInspection
    revision: int

    @property
    def name(self):
        return self.inspection.owner.name

    @property
    def root(self):
        return str(self.inspection.service.root)

    def observed_at(self, revision) -> bool:
        return self.revision == revision

    def observe(self, revision) -> InspectionState:
        return replace(self, revision=revision)

    def same_source(self, inspection) -> bool:
        return inspection.same_native_source(self.inspection)

    def inspection_differs(self, inspection) -> bool:
        return not self.same_source(inspection) or inspection.changed_since(self.inspection)

    def needs_native(self, inspection, force) -> bool:
        return force or self.inspection_differs(inspection)

    def present(self, consumer) -> None:
        consumer(self)

    def groups(self):
        return (("Recorded requests · source evidence, not today's base", self.inspection.recorded(), False),)

    def prepare_native(self, consumer) -> None:
        consumer(self)

    def with_native(self, inspection, native) -> InspectionState:
        return NativeInspection(self.inspection, self.revision, native) if self.same_source(inspection) else self

    def native_failed(self, inspection, error) -> InspectionState:
        return UnavailableNativeInspection(self.inspection, self.revision, str(error)) if self.same_source(inspection) else self

    def current_roots(self):
        raise ValueError("Current native context is not loaded; a selected recorded request can be read separately")

    async def find(self, query, selected):
        roots = selected.search_roots if selected is not None else ContextNode.search_roots
        sources = await Coordination.run_worker(partial(roots, self.current_roots))
        return await self.inspection.find(sources, query)

    def native_matches(self, current):
        return not current.contains_native(bool)

    def search_current(self, captured) -> bool:
        return self.same_source(captured.inspection) and captured.native_matches(self)

    @property
    def status(self):
        return f"{self.name} · recorded manifests available\nReading native context…"


@dataclass(frozen=True)
class NativeInspection(HoldingInspection):
    native: NativeContextData

    def receive_inspection(self, acquired) -> InspectionState:
        if self.same_source(acquired.inspection):
            return NativeInspection(acquired.inspection, acquired.revision, self.native)
        return acquired

    def needs_native(self, inspection, force) -> bool:
        return force or not self.same_source(inspection)

    def with_native(self, inspection, native) -> InspectionState:
        if not self.same_source(inspection) or native == self.native:
            return self
        return NativeInspection(self.inspection, self.revision, native)

    async def refresh_contributors(self, consumer) -> None:
        native = await Coordination.run_worker(partial(self.native.with_current_contributors,
            self.inspection.service, self.inspection.owner))
        consumer(self, native)

    def with_contributors(self, expected, native) -> InspectionState:
        if (self.same_source(expected.inspection) and self.native is expected.native
                and native.contributors != self.native.contributors):
            return NativeInspection(self.inspection, self.revision, native)
        return self

    def groups(self):
        return (
            ("Current Core instructions · before next input", self.inspection.contributors(self.native), True),
            ("Current native base · before next input and provider hooks", self.inspection.active(self.native), True),
            *super().groups(),
        )

    def current_roots(self):
        return (*self.inspection.contributors(self.native), *self.inspection.active(self.native))

    def contains_native(self, matches) -> bool:
        return matches(self.native)

    def native_matches(self, current):
        return current.contains_native(lambda native: native is self.native)

    @property
    def status(self):
        return (f"{self.name} · current Core instructions and native base before future input/provider hooks\n"
                f"Segment counts: estimates ({self.native.counter}) · provider totals unavailable")


@dataclass(frozen=True)
class UnavailableNativeInspection(HoldingInspection):
    error: str

    def receive_inspection(self, acquired) -> InspectionState:
        if self.same_source(acquired.inspection):
            return UnavailableNativeInspection(acquired.inspection, acquired.revision, self.error)
        return acquired

    @property
    def status(self):
        return f"{self.name} · recorded manifests only\nCurrent detail unavailable: {self.error}"
