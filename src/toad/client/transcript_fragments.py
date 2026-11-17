"""Transcript fragments at the shared layer: event projection, render budget and the
neutral fragment family (base, tool, context, bus message, sent message). A backend subclass
adds whatever it needs for its own drawing (Textual row acquisition, Qt row-paint cache, ...);
the data, fragment hierarchy and the consumer-friendly blocks derivation live here so every
frontend sees the same tool calls, context records, bus messages and sent-text events.

The Textual frontend's row-acquisition subclasses and the Consumer that builds those
subclasses live in `toad.widgets.transcript_fragments`; a Qt frontend's siblings live in
`toad.qt.history`. Paper1 Corollary 4.12: both backends inherit these neutral bases rather
than restating the family under each toolkit.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cached_property
from typing import ClassVar

from agent_comms.messaging.sent_message import PublishedSentMessage
from agent_comms.nominal.field_codec import ToolCallId
from agent_comms.storage.recorded_time import EventTime
from agent_comms.transcript.transcript_events import (
    AgentTextTranscript,
    SentTranscript,
    ThinkingTranscript,
    ToolTranscript,
    TranscriptEvent,
    UserTranscript,
)
from metaclass_registry.mro_dispatch import handles

from toad.acp.status import ToolCallStatus
from toad.client.fragments import (
    BusMessageHistoryFragment,
    HistoryFragment,
    PartPosition,
    Shown,
)
from toad.client.line_blocks import (
    AgentRole,
    Body,
    Divider,
    LineBlock,
    LineRole,
    MarkdownMessageBody,
    MessageBody,
    MutedRole,
    UserRole,
)
from toad.commit_claims import CommitClaim
from toad.core.projection import MroProjection
from toad.markdown_preparation import PreparedMarkdownPart
from toad.menus import MenuCommand, message_menu
from toad.tool_output import SentMessageToolOutputPart, ToolOutput, ToolOutputPart
from toad.widgets.agent_activity import AgentActivityPresentation


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
        for index, row in enumerate(lines[2 : table.map[1]], 2):
            if index > first and (
                index - first >= row_limit or len(header) + row_characters + len(row) > character_limit
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

        top_level = [(token.map[0], index, token.type) for index, token in enumerate(source.tokens)
                     if token.level == 0 and token.map is not None]
        token_at = {0: 0, len(lines): len(source.tokens)} | {line: index for line, index, _ in top_level}
        tables = {line for line, _, kind in top_level if kind == "table_open"}
        starts = sorted({0, *token_at, len(lines)})
        parts = [(start, stop, token_at[start], token_at[stop], start in tables)
                 for start, stop in zip(starts, starts[1:])]
        pending_first = 0
        pending_stop = 0
        pending_token_first = 0
        pending_token_stop = 0
        pending_characters = 0
        pending_lines = 0

        def select(first: int, stop: int, token_first: int, token_stop: int):
            return source.select_blocks(text[offsets[first] : offsets[stop]], first, slice(token_first, token_stop))

        for start, stop, token_first, token_stop, is_table in parts:
            part = text[offsets[start] : offsets[stop]]
            if is_table and (len(part) > self.characters or part.count("\n") > self.lines):
                if pending_characters:
                    yield select(pending_first, pending_stop, pending_token_first, pending_token_stop)
                    pending_characters = 0
                    pending_lines = 0
                yield from self._split_table(select(start, stop, token_first, token_stop))
                continue
            part_lines = part.count("\n") + int(bool(part) and not part.endswith("\n"))
            exceeds = pending_characters and (
                pending_characters + len(part) > self.characters or pending_lines + part_lines > self.lines
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


class FragmentLineConsumer(MroProjection[None]):
    """Turn a fragment's events into line blocks, one handler per event family."""

    def __init__(self, *, part: PartPosition) -> None:
        self.part = part
        self.blocks: list[LineBlock] = []
        self.header: tuple[Divider, ...] = ()
        self.header_end = 0

    def divider(self, label: str, timestamp: float, role: type[LineRole]) -> None:
        """The first event's divider is the fragment's message header, drawn or not."""
        divider = Divider.titled(label, role, EventTime.capture(timestamp))
        self.header = self.header or (divider,)
        self.part.draw_divider(self, divider)

    @handles(TranscriptEvent)
    def other(self, event: TranscriptEvent) -> None:
        """Events without visible text in committed history draw nothing."""

    @handles(UserTranscript)
    def user(self, event: UserTranscript) -> None:
        self.divider("User", event.timestamp, UserRole)
        self.blocks += MessageBody(event.text, bar=UserRole).presentation()

    @handles(AgentTextTranscript)
    def agent(self, event: AgentTextTranscript) -> None:
        self.divider("Agent", event.timestamp, AgentRole)
        self.blocks += MarkdownMessageBody(event.text).presentation()

    @handles(SentTranscript)
    def sent_report(self, event: SentTranscript) -> None:
        self.blocks.extend(SentMessageToolOutputPart.capture(event).line_blocks)

    @handles(ThinkingTranscript)
    def thinking(self, event: ThinkingTranscript) -> None:
        if event.text.strip():
            self.blocks += AgentActivityPresentation.thinking(event.text)


@dataclass
class TranscriptFragment(HistoryFragment):
    """The toolkit-neutral base for a transcript fragment: events in, line blocks out.
    Each backend's subclass layers on whatever its draw path requires."""

    @classmethod
    def text_parts(cls, source: PreparedMarkdownPart, budget: RenderBudget):
        return tuple(budget.split(source))

    def sticky_header(self, block: int, row: int) -> tuple[Divider, ...]:
        """The header to pin over the window's top row, which is `row` of block `block`."""
        consumed = self.consumed
        return consumed.header if (block, row) > (consumed.header_end - 1, 0) else ()

    @cached_property
    def consumed(self) -> FragmentLineConsumer:
        """This fragment's events projected once; the blocks do not depend on how it is shown."""
        consumer = FragmentLineConsumer(part=self.part_position)
        if self.starts_agent_activity:
            consumer.blocks.extend(AgentActivityPresentation.group)
        for event in self.events:
            consumer.project_value(event)
        return consumer

    def blocks(self, shown: Shown) -> tuple[LineBlock, ...]:
        """What this fragment draws in committed history when shown so."""
        return tuple(self.consumed.blocks)

    @property
    def block_menu(self) -> tuple[MenuCommand, ...]:
        """What the cursor's menu offers on this fragment, besides copying."""
        return ()


@dataclass(kw_only=True)
class ToolTranscriptFragment(TranscriptFragment):
    """One tool call with everything it reported: a title line, and its output when opened."""

    events: tuple[ToolTranscript, ...] = field(kw_only=False)
    tool_call: ToolCallStatus
    output_parts: tuple[ToolOutputPart, ...]

    @property
    def source_identity(self) -> ToolCallId:
        return self.events[0].tool_call_id

    @property
    def has_details(self) -> bool:
        return AgentActivityPresentation.tool_has_details(
            self.tool_call, any(part.has_details for part in self.output_parts)
        )

    def blocks(self, shown: Shown):
        return AgentActivityPresentation.tool(
            self.tool_call,
            has_details=self.has_details,
            details_open=shown.details_open,
            details=(block for part in self.output_parts for block in part.line_blocks),
            details_link=self.details_link,
        )


@dataclass(kw_only=True)
class BusMessageFragment(BusMessageHistoryFragment, TranscriptFragment):
    """A bus message drawn from transcript events: header, menu, body paging."""

    @classmethod
    def text_parts(cls, source: PreparedMarkdownPart, budget: RenderBudget):
        # Even an empty bus message owns its header and notification footer.
        return super().text_parts(source, budget) or (source,)

    @property
    def block_menu(self):
        return message_menu(self.row)

    def sticky_header(self, block: int, row: int) -> tuple[Divider, ...]:
        """Every part of a message pins its header once the header's first row is above the top
        row, which is `row` of block `block`; a later part draws no header, so it always pins."""
        return (self.row.header,) if (block, row) > (len(self.leading) - 1, 0) else ()


@dataclass(kw_only=True)
class SentMessageFragment(BusMessageFragment):
    publication: PublishedSentMessage

    @property
    def outgoing_sources(self):
        return self.part_position.outgoing_sources(self.publication)

    def shown_live_by(self, claim: CommitClaim) -> bool:
        return claim.repeats_sent(self.publication.reference)


class ContextTranscriptFragment(TranscriptFragment):
    """The coordination context an agent was given: one line, and its text when opened."""

    has_details: ClassVar[bool] = True

    def blocks(self, shown):
        summary = shown.summary("Agent coordination context", MutedRole, self.details_link)
        if not shown.details_open:
            return (summary,)
        return (summary, *(Body(event.text, role=MutedRole, bar=MutedRole) for event in self.events))
