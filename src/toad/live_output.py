"""Transient live streams own their blocks; saved history has a separate owner."""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Collection
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from toad.widgets.agent_response import AgentResponse, ResponseDelivery, UnroutedResponse
from toad.widgets.agent_thought import AgentThought

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation
    from textual.widget import Widget


class OutputStream(ABC):
    """One declared live output case and the block receiving its fragments."""

    def __init__(self) -> None:
        self.block: AgentResponse | AgentThought | None = None

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
                self.block = self.create(fragment)
                await view.post(self.block, new_block=False)
        else:
            await self.block.append_fragment(fragment)
        return self.block

    async def finish(self) -> None:
        block, self.block = self.block, None
        if block is not None:
            await block.finish_stream()

    async def settle(self) -> None:
        pass


class ResponseStream(OutputStream):
    def __init__(self, delivery: ResponseDelivery = UnroutedResponse(), *, turn_id: str | None = None) -> None:
        super().__init__()
        self.delivery = delivery
        self.turn_id = turn_id

    async def before_append(self, output: LiveOutput) -> None:
        await output.finish(ThoughtStream)

    def matches(self, incoming: ResponseStream) -> bool:
        return self.delivery == incoming.delivery and self.turn_id == incoming.turn_id

    def create(self, fragment: str) -> AgentResponse:
        return AgentResponse(fragment, delivery=self.delivery)


class CompleteResponseStream(ResponseStream):
    """An owner notice is complete at ingress rather than awaiting a turn end."""
    async def append(self, view, fragment):
        block = await super().append(view, fragment)
        await self.finish()
        return block


class CompactionStream(OutputStream):
    """A provisional summary body belongs to its selected native operation."""

    def __init__(self, operation_id: str):
        super().__init__()
        self.operation_id = operation_id

    def matches(self, incoming: CompactionStream) -> bool:
        return self.operation_id == incoming.operation_id

    def create(self, fragment: str) -> AgentResponse:
        from toad.widgets.message_filter import OtherCategory
        return AgentResponse("## Compaction summary · draft\n\n" + fragment,
                             category=OtherCategory)

    async def finish(self) -> None:
        block, self.block = self.block, None
        if block is not None:
            await block.finish_stream()
            await block.remove()


class ThoughtStream(OutputStream):
    def accepts(self, fragment: str) -> bool:
        return bool(fragment.strip())

    def matches(self, incoming: ThoughtStream) -> bool:
        return True

    def create(self, fragment: str) -> AgentThought:
        return AgentThought(fragment)

    async def settle(self) -> None:
        if self.block is not None and self.block.loading:
            await self.block.remove()


class LiveOutput:
    """Owns admitted streams, serialized posting and rich-view retirement."""

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
        """A source commit retires only streams whose actual blocks it replaces."""
        async with self.lock:
            for kind, stream in tuple(self.streams.items()):
                if stream.block in candidates:
                    await self.finish(kind)

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
