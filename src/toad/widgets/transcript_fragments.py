"""Render-sized transcript fragments; wire records and cursors remain model-owned."""

import asyncio
from dataclasses import dataclass, replace
from functools import cached_property
from collections.abc import Iterator
from typing import TYPE_CHECKING
from threading import local

from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.transcript_events import (
    TranscriptEvent, TextTranscript, ContextTranscript, UserTranscript, MarkdownTranscript, ToolTranscript,
)
from markdown_it import MarkdownIt

from toad.render_backend import ReusableRenderTask
from toad.widgets.agent_activity import AgentActivityBoundary
from toad.widgets.message_filter import event_category

if TYPE_CHECKING:
    from toad.render_backend import Renderer

class _FragmentParserState(local):
    def __init__(self) -> None:
        self.parser = MarkdownIt("gfm-like")


_parser_state = _FragmentParserState()


def _fragment_parser() -> MarkdownIt:
    """Reuse parser machinery within one execution thread, never concurrently."""
    return _parser_state.parser


async def prepare_transcript_fragments(
    events: tuple[TranscriptEvent, ...], pool: "Renderer | None" = None,
    *, continuation: bool = False,
) -> tuple["TranscriptFragment", ...]:
    """Prepare plain model data; never send widgets or application state to workers.

    Standalone Textual apps may not own a pool. Their large requests own and close
    a temporary pool, including on cancellation; there is no hidden global pool.
    """
    if pool is not None:
        return await pool.submit(TranscriptRenderTask(events, continuation=continuation))
    from toad.render_processes import RenderProcessPool

    owned_pool = RenderProcessPool()
    try:
        return await owned_pool.submit(TranscriptRenderTask(events, continuation=continuation))
    finally:
        await owned_pool.aclose()


@dataclass(frozen=True)
class RenderBudget:
    characters: int = 800
    lines: int = 12

    def _split_table(self, text: str) -> Iterator[str]:
        """Page a large GFM table by rows, repeating its required header."""
        lines = text.splitlines(keepends=True)
        if len(lines) <= 2:
            yield text
            return
        header = "".join(lines[:2])
        rows: list[str] = []
        row_characters = 0
        row_limit = max(1, self.lines - 2)
        character_limit = max(self.characters, len(header) + 1)
        for row in lines[2:]:
            if rows and (
                len(rows) >= row_limit
                or len(header) + row_characters + len(row) > character_limit
            ):
                yield header + "".join(rows)
                rows = []
                row_characters = 0
            rows.append(row)
            row_characters += len(row)
        if rows:
            yield header + "".join(rows)

    def split(self, text: str) -> Iterator[str]:
        if not text:
            return
        if (len(text) <= self.characters
                and len(text.splitlines()) <= self.lines):
            # No block can exceed either budget when the entire document fits.
            # Return the unchanged source; there is no partition decision to
            # parse, and normal Markdown rendering still handles its syntax.
            yield text
            return
        lines = text.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))

        # Separate widgets always introduce a visual row boundary. Split only
        # between top-level Markdown blocks so rendering never invents a line
        # break at an arbitrary provider-chunk or character boundary.
        blocks = {
            token.map[0]: token.type
            for token in _fragment_parser().parse(text)
            if token.level == 0 and token.map is not None
        }
        starts = sorted({0, *blocks, len(lines)})
        parts: list[tuple[str, str | None]] = [
            (text[offsets[start] : offsets[stop]], blocks.get(start))
            for start, stop in zip(starts, starts[1:])
        ]
        pending = ""
        pending_lines = 0
        for part, kind in parts:
            if kind == "table_open" and (
                len(part) > self.characters or part.count("\n") > self.lines
            ):
                if pending:
                    yield pending
                    pending = ""
                    pending_lines = 0
                yield from self._split_table(part)
                continue
            part_lines = part.count("\n") + int(bool(part) and not part.endswith("\n"))
            exceeds = (
                pending
                and (
                    len(pending) + len(part) > self.characters
                    or pending_lines + part_lines > self.lines
                )
            )
            if exceeds:
                yield pending
                pending = ""
                pending_lines = 0
            pending += part
            pending_lines += part_lines
        if pending:
            yield pending


@dataclass(frozen=True)
class TranscriptFragment:
    events: tuple[TranscriptEvent, ...]
    continuation: bool = False
    starts_agent_activity: bool = False

    @cached_property
    def retained_bytes(self) -> int:
        """Measure this immutable source resource once, before native admission."""
        from toad.work_preparation import retained_bytes

        return retained_bytes(self)


class TranscriptFragmentConsumer(MroDispatch):
    def __init__(self, *, continuation: bool = False):
        self.fragments: list[TranscriptFragment] = []
        self.tools: dict[str, int] = {}
        self.budget = RenderBudget()
        self.boundary = AgentActivityBoundary()
        self.continuation = continuation

    @handles(ContextTranscript)
    def context(self, event: ContextTranscript):
        # One lazy disclosure owns the full metadata source.
        self.fragments.append(TranscriptFragment((event,), continuation=self.continuation))

    @handles(UserTranscript, MarkdownTranscript)
    def text(self, event: TextTranscript):
        starts_activity = self.boundary.observe(event_category(event)) if event.starts_activity else False
        self.fragments.extend(
            TranscriptFragment((replace(event, text=part),), continuation=self.continuation or index > 0,
                               starts_agent_activity=starts_activity and index == 0)
            for index, part in enumerate(self.budget.split(event.text))
        )

    @handles(ToolTranscript)
    def tool(self, event: ToolTranscript):
        if event.tool_call_id in self.tools:
            index = self.tools[event.tool_call_id]
            self.fragments[index] = replace(self.fragments[index], events=(*self.fragments[index].events, event))
        else:
            self.tools[event.tool_call_id] = len(self.fragments)
            self.fragments.append(TranscriptFragment(
                (event,), continuation=self.continuation,
                starts_agent_activity=self.boundary.observe(event_category(event)),
            ))


def transcript_fragments(
    events: tuple[TranscriptEvent, ...], *, continuation: bool = False,
) -> tuple[TranscriptFragment, ...]:
    consumer = TranscriptFragmentConsumer(continuation=continuation)
    for event in events:
        consumer.dispatch_sync(event)
    # This producer runs in the existing renderer for saved and paged sources.
    # Deliver the measured resource with its source rather than walking nested
    # tool inputs again in every native fragment constructor or publication.
    for fragment in consumer.fragments:
        fragment.retained_bytes
    return tuple(consumer.fragments)


class TranscriptBodyPreparation(MroDispatch):
    """Pure body work for declared transcript cases, without native widgets."""

    def __init__(self, renderer, ansi: bool, dark: bool):
        self.renderer, self.ansi, self.dark = renderer, ansi, dark

    async def prepare_fragments(self, fragments, keep_going, *, batch_size: int) -> None:
        """Warm a bounded source range in shared workers, without native mounts.

        Reversal/retirement stops the next batch. Already admitted render work
        keeps its existing runtime custody and resource limits.
        """
        for first in range(0, len(fragments), batch_size):
            if not keep_going():
                return
            await asyncio.gather(*(self.dispatch(event)
                                   for fragment in fragments[first:first + batch_size]
                                   for event in fragment.events))

    @handles(TranscriptEvent)
    async def undisclosed(self, event: TranscriptEvent) -> None:
        # Metadata and tool disclosure contents retain their existing lazy
        # owners. A viewport prediction does not open those disclosures.
        pass

    @handles(MarkdownTranscript)
    async def markdown(self, event: MarkdownTranscript) -> None:
        from toad.render_tasks import MarkdownRenderTask

        await self.renderer.prepare(MarkdownRenderTask(event.text, self.ansi, self.dark))


@dataclass(frozen=True)
class TranscriptRenderTask(ReusableRenderTask[tuple[TranscriptFragment, ...]]):
    events: tuple[TranscriptEvent, ...]
    continuation: bool = False

    def execute(self) -> tuple[TranscriptFragment, ...]:
        return transcript_fragments(self.events, continuation=self.continuation)

    def accept_result(self, result: object) -> tuple[TranscriptFragment, ...]:
        if not isinstance(result, tuple) or not all(isinstance(item, TranscriptFragment) for item in result):
            raise TypeError("Transcript renderer returned an invalid result")
        return result
