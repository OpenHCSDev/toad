"""Render-sized transcript fragments; wire records and cursors remain model-owned."""

import asyncio
from dataclasses import dataclass, field, replace
from functools import cached_property
from collections.abc import Iterator
from typing import TYPE_CHECKING

from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.transcript_events import (
    TranscriptEvent, TextTranscript, ContextTranscript, UserTranscript, MarkdownTranscript, ToolTranscript,
)

from toad.render_backend import ReusableRenderTask
from toad.markdown_preparation import PreparedContentRange, PreparedMarkdown, PreparedMarkdownPart
from toad.acp.status import ToolCallStatus
from toad.widgets.agent_activity import AgentActivityBoundary
from toad.widgets.message_filter import event_category, keep_events

if TYPE_CHECKING:
    from toad.render_backend import Renderer
    from toad.tool_output import ToolOutputPart

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

    def fits(self, text: str) -> bool:
        return len(text) <= self.characters and len(text.splitlines()) <= self.lines

    def _split_table(self, part: PreparedMarkdownPart) -> Iterator[PreparedMarkdownPart]:
        """Page a large GFM table by rows, repeating its required header."""
        lines = part.text.splitlines(keepends=True)
        if len(lines) <= 2:
            yield part
            return
        header = "".join(lines[:2])
        first = 2
        row_characters = 0
        row_limit = max(1, self.lines - 2)
        character_limit = max(self.characters, len(header) + 1)
        table = part.tokens[0]
        assert table.map is not None
        ranges = []
        for index, row in enumerate(lines[2:table.map[1]], 2):
            if index > first and (
                index - first >= row_limit
                or len(header) + row_characters + len(row) > character_limit
            ):
                ranges.append((first, index))
                first = index
                row_characters = 0
            row_characters += len(row)
        if first < len(lines):
            ranges.append((first, len(lines)))
        yield from part.select_table_rows(ranges)

    def split(self, source: PreparedMarkdownPart) -> Iterator[PreparedMarkdownPart]:
        text = source.text
        if not text:
            return
        if self.fits(text):
            yield source
            return
        lines = text.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))

        # Separate widgets always introduce a visual row boundary. Split only
        # between top-level Markdown blocks so rendering never invents a line
        # break at an arbitrary provider-chunk or character boundary.
        blocks = {
            token.map[0]: (index, token.type)
            for index, token in enumerate(source.tokens)
            if token.level == 0 and token.map is not None
        }
        starts = sorted({0, *blocks, len(lines)})
        parts = [
            (start, stop, blocks.get(start, (0, None))[0],
             blocks.get(stop, (len(source.tokens), None))[0], blocks.get(start, (0, None))[1])
            for start, stop in zip(starts, starts[1:])
        ]
        pending_first = 0
        pending_stop = 0
        pending_token_first = 0
        pending_token_stop = 0
        pending_characters = 0
        pending_lines = 0
        def select(first, stop, token_first, token_stop):
            return source.select_blocks(text[offsets[first]:offsets[stop]], first,
                                        slice(token_first, token_stop))

        for start, stop, token_first, token_stop, kind in parts:
            part = text[offsets[start]:offsets[stop]]
            if kind == "table_open" and (
                len(part) > self.characters or part.count("\n") > self.lines
            ):
                if pending_characters:
                    yield select(pending_first, pending_stop, pending_token_first, pending_token_stop)
                    pending_characters = 0
                    pending_lines = 0
                yield from self._split_table(select(start, stop, token_first, token_stop))
                continue
            part_lines = part.count("\n") + int(bool(part) and not part.endswith("\n"))
            exceeds = (
                pending_characters
                and (
                    pending_characters + len(part) > self.characters
                    or pending_lines + part_lines > self.lines
                )
            )
            if exceeds:
                yield select(pending_first, pending_stop, pending_token_first, pending_token_stop)
                pending_characters = 0
                pending_lines = 0
            if not pending_characters:
                pending_first = start
                pending_token_first = token_first
            pending_stop = stop
            pending_token_stop = token_stop
            pending_characters += len(part)
            pending_lines += part_lines
        if pending_characters:
            yield select(pending_first, pending_stop, pending_token_first, pending_token_stop)


@dataclass
class TranscriptFragment:
    events: tuple[TranscriptEvent, ...]
    continuation: bool = False
    starts_agent_activity: bool = False
    markdown_part: PreparedMarkdownPart | None = field(default=None, kw_only=True)
    prepared_source: PreparedMarkdown | None = field(default=None, kw_only=True, compare=False, repr=False)
    prepared_content: PreparedContentRange | None = field(default=None, kw_only=True, compare=False, repr=False)

    def line_blocks(self, styles, *, show_divider: bool = True):
        """This fragment's committed-history lines, one block per visual part."""
        from toad.widgets.transcript_lines import FragmentLineConsumer, Summary

        consumer = FragmentLineConsumer(styles, show_divider=show_divider)
        if self.starts_agent_activity and not self.continuation:
            consumer.blocks.append(Summary("· Agent activity", styles.muted))
        for event in self.events:
            consumer.dispatch_sync(event)
        return tuple(consumer.blocks)

    def lines_for(self, width: int, styles):
        """Styled lines this fragment holds for a width and theme, if any."""
        held = self.__dict__.get("_lines")
        return held[1] if held is not None and held[0] == styles and held[1].width == width else None

    def hold_lines(self, styles, lines) -> None:
        self.__dict__["_lines"] = styles, lines

    def resolved_sources(self):
        return (() if self.prepared_source is None else self.prepared_source.resolved_sources()) + (
            () if self.prepared_content is None else self.prepared_content.resolved_sources())

    async def prepare(self, renderer, ansi, dark):
        # These are the source suppliers that reconstruction actually uses.
        # Undisclosed metadata/tool sources have no eager Markdown supply.
        source = self.prepared_source or self.prepared_content or self.markdown_part
        if source is not None:
            await source.prepare(renderer, ansi, dark)

    def independent(self) -> "TranscriptFragment":
        """A separate projection owns independently resolved source lifetimes."""
        return self._independent(prepared_source=None, prepared_content=None)

    def _independent(self, **changes):
        source = replace(self, **changes)
        # Measurement belongs to immutable input; acquisitions never enter it.
        source.__dict__["retained_bytes"] = self.retained_bytes
        return source

    @cached_property
    def retained_bytes(self) -> int:
        """Worker-owned immutable input cost, never an acquisition graph."""
        from toad.work_preparation import retained_bytes

        return retained_bytes(self)


@dataclass(kw_only=True)
class ToolTranscriptFragment(TranscriptFragment):
    """One original grouped tool and its worker-acquired ACP presentation."""

    tool_call: ToolCallStatus
    output_parts: "tuple[ToolOutputPart, ...]"

    def line_blocks(self, styles, *, show_divider: bool = True):
        from toad.widgets.transcript_lines import Summary

        return (Summary(f"▶ {self.tool_call.call.title or 'Tool'}", styles.muted),)

    def resolved_sources(self):
        return tuple(source for part in self.output_parts for source in part.resolved_sources())

    def independent(self):
        return self._independent(output_parts=tuple(part.admit() for part in self.output_parts))

@dataclass(kw_only=True)
class ContextTranscriptFragment(TranscriptFragment):
    """One original lazy disclosure and its two distinct source ranges."""

    formatted: str | None = field(default=None, compare=False, repr=False)
    original_content: PreparedContentRange | None = field(default=None, compare=False, repr=False)

    async def prepare(self, renderer, ansi, dark):
        # Returning a retained disclosure does not open either of its sources.
        return

    def line_blocks(self, styles, *, show_divider: bool = True):
        from toad.widgets.transcript_lines import Summary

        return (Summary("▶ Agent coordination context", styles.muted),)

    def resolved_sources(self):
        return super().resolved_sources() + (() if self.original_content is None else
                                             self.original_content.resolved_sources())

    def independent(self):
        return self._independent(prepared_content=None, original_content=None)


class TranscriptFragmentConsumer(MroDispatch):
    def __init__(self, *, continuation: bool = False, split_text: bool = True):
        self.fragments: list[TranscriptFragment] = []
        self.tools: dict[str, int] = {}
        self.budget = RenderBudget()
        self.boundary = AgentActivityBoundary()
        self.continuation = continuation
        self.split_text = split_text

    @handles(ContextTranscript)
    def context(self, event: ContextTranscript):
        # One lazy disclosure owns the full metadata source.
        self.fragments.append(ContextTranscriptFragment((event,), continuation=self.continuation))

    @handles(UserTranscript, MarkdownTranscript)
    def text(self, event: TextTranscript):
        starts_activity = self.boundary.observe(event_category(event)) if event.starts_activity else False
        source = PreparedMarkdownPart.capture(event.text)
        self.fragments.extend(
            TranscriptFragment((replace(event, text=part.text),), continuation=self.continuation or index > 0,
                               starts_agent_activity=starts_activity and index == 0, markdown_part=part)
            for index, part in enumerate(self.budget.split(source) if self.split_text else (source,))
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
    events: tuple[TranscriptEvent, ...], *, continuation: bool = False, split_text: bool = True,
) -> tuple[TranscriptFragment, ...]:
    consumer = TranscriptFragmentConsumer(continuation=continuation, split_text=split_text)
    for event in events:
        consumer.dispatch_sync(event)
    # Grouping belongs to this producer. Decode once after the final event,
    # before storage/byte accounting and before any native reconstruction.
    for index in consumer.tools.values():
        from toad.tool_output import ToolOutput

        source = consumer.fragments[index]
        call = ToolCallStatus.from_transcript(source.events)
        consumer.fragments[index] = ToolTranscriptFragment(
            source.events, continuation=source.continuation,
            starts_agent_activity=source.starts_agent_activity,
            tool_call=call, output_parts=ToolOutput.capture_parts(call.call),
        )
    # This producer runs in the existing renderer for saved and paged sources.
    # Deliver the measured resource with its source rather than walking nested
    # tool inputs again in every native fragment constructor or publication.
    for fragment in consumer.fragments:
        fragment.retained_bytes
    return tuple(consumer.fragments)


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
