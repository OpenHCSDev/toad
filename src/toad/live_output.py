"""Transient live streams own their blocks; saved history has a separate owner."""

from __future__ import annotations

import asyncio
import weakref
from abc import abstractmethod
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily

from toad.response_delivery import ResponseDelivery, UnroutedResponse
from toad.widgets.committed_presentation import CAPTURED_CLAIM, CapturedClaim

if TYPE_CHECKING:
    from textual.widget import Widget

    from toad.widgets.agent_response import AgentResponse
    from toad.widgets.agent_thought import AgentThought
    from toad.widgets.conversation import Conversation


@dataclass
class OutputStream(DeclaredFamily, affix="Stream"):
    """One declared live output case and the block receiving its fragments."""

    source_claim: CapturedClaim = field(default_factory=lambda: CAPTURED_CLAIM, kw_only=True)

    def __post_init__(self) -> None:
        self.block = None

    async def before_append(self, output: LiveOutput) -> None:
        pass

    def accepts(self, fragment: str) -> bool:
        return True

    @abstractmethod
    def matches(self, incoming: OutputStream) -> bool: ...

    @abstractmethod
    def create(self, fragment: str) -> AgentResponse | AgentThought: ...

    async def append(self, view: Conversation, fragment: str):
        if self.block is None:
            if self.accepts(fragment):
                block = self.create(fragment)
                block.source_claim = self.source_claim
                self.block = block
                await view.post(block, new_block=False)
        else:
            await self.block.append_fragment(fragment)
        return self.block

    async def finish(self) -> None:
        block, self.block = self.block, None
        if block is not None:
            await block.finish_stream()

    async def settle(self) -> None:
        pass


@dataclass
class ResponseStream(OutputStream):
    delivery: ResponseDelivery = field(default_factory=UnroutedResponse)
    turn_id: str | None = field(default=None, kw_only=True)

    async def before_append(self, output: LiveOutput) -> None:
        await output.finish(ThoughtStream)

    def matches(self, incoming: ResponseStream) -> bool:
        return (self.delivery == incoming.delivery and self.turn_id == incoming.turn_id
                and self.source_claim is incoming.source_claim)

    def create(self, fragment: str) -> AgentResponse:
        from toad.widgets.agent_response import AgentResponse
        return AgentResponse(fragment, delivery=self.delivery)


class CompleteResponseStream(ResponseStream):
    """A declared standalone notice closes the preceding reply and its own block."""

    async def before_append(self, output: LiveOutput) -> None:
        await super().before_append(output)
        await output.finish(ResponseStream)

    async def append(self, view, fragment):
        block = await super().append(view, fragment)
        await self.finish()
        return block


class ThoughtStream(OutputStream):
    def accepts(self, fragment: str) -> bool:
        return bool(fragment.strip())

    def matches(self, incoming: ThoughtStream) -> bool:
        return self.source_claim is incoming.source_claim

    def create(self, fragment: str) -> AgentThought:
        from toad.widgets.agent_thought import AgentThought
        return AgentThought(fragment)

    async def settle(self) -> None:
        if self.block is not None and self.block.loading:
            await self.block.remove()


class LiveOutput:
    """Owns accepted streams, serialized posting and rich-view retirement."""

    def __init__(self, view: Conversation) -> None:
        self._view = weakref.ref(view)
        self.streams: dict[type[OutputStream], OutputStream] = {}
        self.lock = asyncio.Lock()
        self.revision = 0

    async def append(self, incoming: OutputStream, fragment: str):
        async with self.lock:
            view = self._view()
            if view is None or not view.is_attached:
                return None
            revision = self.revision
            await incoming.before_append(self)
            stream = self.streams.get(type(incoming))
            if stream is not None and not stream.matches(incoming):
                await self.finish(type(incoming))
                stream = None
            if revision != self.revision or self._view() is not view or not view.is_attached:
                return None
            if stream is None:
                stream = self.streams[type(incoming)] = incoming
            return await stream.append(view, fragment)

    async def finish(self, kind: type[OutputStream]) -> None:
        stream = self.streams.pop(kind, None)
        if stream is not None:
            await stream.finish()

    async def settle(self) -> None:
        for stream in tuple(self.streams.values()):
            await stream.settle()

    async def retire_presentations(self, candidates: Collection[Widget]) -> None:
        """Transfer covered blocks to the source owner's native retirement.

        Their accepted saved rows already own the content. Flushing another
        append here can reenter that source's history lock while publication
        holds it. Native Prune closes the original block's workers and stream;
        the publication owner joins that teardown before releasing its fence.
        Turn settlement still drains streams through finish().
        """
        async with self.lock:
            for kind, stream in tuple(self.streams.items()):
                if stream.block in candidates:
                    self.streams.pop(kind)

    def boundary(self) -> None:
        self.revision += 1
        streams, self.streams = self.streams, {}
        if (view := self._view()) is not None:
            for stream in streams.values():
                view.call_later(stream.finish)

    def retire(self) -> None:
        self.revision += 1
        self.streams.clear()
        self._view = lambda: None
