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

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from functools import cached_property, partial
from typing import ClassVar

from agent_comms.messaging.message_reference import MessageReference
from agent_comms.messaging.sent_message import PublishedSentMessage
from agent_comms.nominal.field_codec import ToolCallId
from agent_comms.storage.recorded_time import EventTime
from agent_comms.transcript.transcript_events import (
    AgentTextTranscript,
    ContextTranscript,
    IncomingTranscript,
    MarkdownTranscript,
    SentTranscript,
    TextTranscript,
    ThinkingTranscript,
    ToolTranscript,
    TranscriptEvent,
    UserTranscript,
)
from agent_comms.ui_model.message_category import AgentActivityBoundary
from metaclass_registry.mro_dispatch import handles

from toad.acp.status import ToolCallStatus
from toad.client.fragments import (
    BusMessageHistoryFragment,
    HistoryFragment,
    PartPosition,
    Shown,
)
from toad.client.message_file_links import NO_PAGE_FILES, FileReader, PageFiles
from toad.message_rows import MessageRow
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
from toad.client.agent_activity import AgentActivityPresentation
from toad.client.structured_context import has_structured_tags, parse_structured_text


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
        if has_structured_tags(event.text):
            for part in parse_structured_text(event.text):
                self.blocks += part.line_blocks()
        else:
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
        """The header to pin over the window's top row, which is `row` of block `block`: once
        the header's last block has its first row above the top row."""
        return self.pinned_dividers if (block, row) > (self.header_blocks - 1, 0) else ()

    @property
    def header_blocks(self) -> int:
        """How many of this fragment's leading line blocks its header is. Only those decide
        the pin (`sticky_header`): a top row in any later block pins the same header, so a
        frontend locating the top row need not measure past them."""
        return self.consumed.header_end

    @property
    def pinned_dividers(self) -> tuple[Divider, ...]:
        """The header a top row past the header blocks pins."""
        return self.consumed.header

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

    @property
    def header_blocks(self) -> int:
        """Every part of a message pins its header once its leading blocks' first row is above
        the top row; a later part has no leading blocks, so it always pins."""
        return len(self.leading)

    @property
    def pinned_dividers(self) -> tuple[Divider, ...]:
        return (self.row.header,)


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
        summary = shown.summary("Context", MutedRole, self.details_link)
        if not shown.details_open:
            return (summary,)
        return (summary, *(Body(event.text, role=MutedRole, bar=MutedRole) for event in self.events))


type ResolvedSent = Mapping[SentTranscript, SentTranscript | PublishedSentMessage]


@dataclass(frozen=True)
class FragmentClasses:
    """The subclass flavors each backend builds. Both frontends share the consumer, builder
    and slot family here; what differs is the concrete subclasses they want constructed
    (Textual's draw-path layer, or Qt's row-paint layer). The consumer reads these refs
    rather than naming the subclasses directly, so no draw-path shim is sneaked into the
    shared layer."""

    transcript: type[TranscriptFragment]
    context: type[ContextTranscriptFragment]
    bus_message: type[BusMessageFragment]
    sent_message: type[SentMessageFragment]
    tool: type[ToolTranscriptFragment]


class FragmentSlot(ABC):
    """One place in a page's fragment order, and what it holds once sent reports are resolved."""

    def sent_reports(self) -> tuple[SentTranscript, ...]:
        """The sent rows whose publication evidence this slot needs."""
        return ()

    def fragments(self, resolved: ResolvedSent) -> tuple[TranscriptFragment, ...]:
        return self.unresolved()

    @abstractmethod
    def unresolved(self) -> tuple[TranscriptFragment, ...]:
        """The fragments as read, before any publication evidence."""


@dataclass(frozen=True)
class BuiltSlot(FragmentSlot):
    """A fragment built as its event was read."""

    fragment: TranscriptFragment

    def unresolved(self) -> tuple[TranscriptFragment, ...]:
        return (self.fragment,)


@dataclass(frozen=True)
class SentSlot(BuiltSlot):
    """A sent wire row: resolved, it is what its publication evidence builds."""

    report: SentTranscript
    classes: FragmentClasses
    files: PageFiles

    def sent_reports(self) -> tuple[SentTranscript, ...]:
        return (self.report,)

    def fragments(self, resolved: ResolvedSent) -> tuple[TranscriptFragment, ...]:
        builder = TranscriptFragmentConsumer(self.classes, self.files)
        builder.project_value(resolved[self.report])
        return builder.unresolved()


@dataclass(frozen=True)
class TextSlot(FragmentSlot):
    """A text event, parsed and split only when its fragments are asked for."""

    event: TextTranscript
    kind: type[TranscriptFragment]
    budget: RenderBudget
    starts_activity: bool
    options: Mapping[str, object]

    def unresolved(self) -> tuple[TranscriptFragment, ...]:
        parts = self.kind.text_parts(PreparedMarkdownPart.capture(self.event.text), self.budget)
        return tuple(
            self.kind.capture_part(
                self.event,
                part.text,
                part_position=position,
                starts_agent_activity=position.starts_activity(self.starts_activity),
                **self.options,
            )
            for part, position in zip(parts, PartPosition.sequence(len(parts)), strict=True)
        )


@dataclass(eq=False)
class ToolSlot(FragmentSlot):
    """One tool call's events, gathered in the place of its first event."""

    starts_activity: bool
    classes: FragmentClasses
    events: list[ToolTranscript] = field(default_factory=list)

    @cached_property
    def call(self) -> ToolCallStatus:
        return ToolCallStatus.from_transcript(tuple(self.events))

    @cached_property
    def parts(self) -> tuple[ToolOutputPart, ...]:
        return ToolOutput.capture_recorded(self.call, tuple(self.events))

    def sent_reports(self) -> tuple[SentTranscript, ...]:
        return tuple(message for part in self.parts for message in part.sent_reports)

    def fragments(self, resolved: ResolvedSent) -> tuple[TranscriptFragment, ...]:
        parts = self.call.project_output(self.parts, partial(ToolOutput.apply_sent, resolved=resolved))
        return (self.classes.tool(tuple(self.events), starts_agent_activity=self.starts_activity,
                                  tool_call=self.call, output_parts=parts),)

    def unresolved(self) -> tuple[TranscriptFragment, ...]:
        return self.fragments({})


class BusMessageRow(MroProjection[tuple[MessageRow, ...]]):
    """The bus message a transcript event draws, as its row: a received message read by its
    recipient, a sent one once resolved read by the recipient it was published to. Every
    other event, a sent report not yet resolved included, draws none."""

    @handles(IncomingTranscript)
    def incoming(self, event: IncomingTranscript) -> tuple[MessageRow, ...]:
        return (MessageRow(event.message, event.reader),)

    @handles(PublishedSentMessage)
    def published(self, message: PublishedSentMessage) -> tuple[MessageRow, ...]:
        return (MessageRow(message.original, message.scope.recipient.name),)

    @handles(TranscriptEvent)
    def other(self, event: TranscriptEvent) -> tuple[MessageRow, ...]:
        return ()


BUS_MESSAGE_ROW = BusMessageRow()


class TranscriptFragmentConsumer(MroProjection[None]):
    """Build a frontend's fragment family from a stream of transcript events. The frontend
    picks which subclasses to construct by passing its `FragmentClasses`; Textual passes
    `TEXTUAL_FRAGMENT_CLASSES` from `widgets/transcript_fragments.py`, Qt passes its own."""

    def __init__(self, classes: FragmentClasses, files: PageFiles) -> None:
        self.classes = classes
        self.files = files
        self.slots: list[FragmentSlot] = []
        self.tools: dict[str, ToolSlot] = {}
        self.budget = RenderBudget()
        self.boundary = AgentActivityBoundary()

    def unresolved(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for slot in self.slots for fragment in slot.unresolved())

    @handles(ContextTranscript)
    def context(self, event: ContextTranscript) -> None:
        # One lazy disclosure owns the full metadata source.
        self.slots.append(BuiltSlot(self.classes.context((event,))))

    @handles(IncomingTranscript)
    def incoming(self, event: IncomingTranscript) -> None:
        (row,) = BUS_MESSAGE_ROW.project_value(event)
        self.text(event, self.classes.bus_message, row=row, files=self.files.of(row.message.reference))

    @handles(SentTranscript)
    def sent(self, event: SentTranscript) -> None:
        self.slots.append(SentSlot(self.classes.transcript((event,)), event, self.classes, self.files))

    @handles(PublishedSentMessage)
    def published(self, message: PublishedSentMessage) -> None:
        (row,) = BUS_MESSAGE_ROW.project_value(message)
        self.text(
            message.message,
            self.classes.sent_message,
            publication=message,
            row=row,
            files=self.files.of(row.message.reference),
        )

    @handles(UserTranscript, MarkdownTranscript)
    def text(self, event: TextTranscript, kind: type[TranscriptFragment] | None = None, **kwargs) -> None:
        starts_activity = self.boundary.observe(event.category) if event.starts_activity else False
        self.slots.append(TextSlot(event, kind or self.classes.transcript, self.budget, starts_activity, kwargs))

    @handles(ToolTranscript)
    def tool(self, event: ToolTranscript) -> None:
        if event.tool_call_id not in self.tools:
            # The call keeps the place of its first event.
            self.tools[event.tool_call_id] = slot = ToolSlot(self.boundary.observe(event.category), self.classes)
            self.slots.append(slot)
        self.tools[event.tool_call_id].events.append(event)


@dataclass(frozen=True)
class FragmentPlan:
    """Events read into their slots with their sent reports resolved, before any markdown parse."""

    slots: tuple[FragmentSlot, ...] = ()
    resolved: ResolvedSent = field(default_factory=dict)

    @classmethod
    def read(
        cls,
        events: tuple[TranscriptEvent, ...],
        *,
        resolve_sent: Callable[[Iterable[SentTranscript]], ResolvedSent],
        classes: FragmentClasses,
        files: PageFiles,
    ) -> FragmentPlan:
        consumer = TranscriptFragmentConsumer(classes, files)
        for event in events:
            consumer.project_value(event)
        resolved = resolve_sent(report for slot in consumer.slots for report in slot.sent_reports())
        return cls(tuple(consumer.slots), resolved)

    @classmethod
    def for_draft(cls, draft, identity, classes: FragmentClasses) -> FragmentPlan:
        """Core's in-progress CLI draft, read as committed events are, its sent reports
        resolved against the read identity's wire frontier."""
        return cls.read(draft.events, resolve_sent=identity.wire_frontier.resolve_sent_messages,
                        classes=classes, files=NO_PAGE_FILES)

    def fragments(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for slot in self.slots for fragment in slot.fragments(self.resolved))


def transcript_fragments(
    events: tuple[TranscriptEvent, ...],
    *,
    resolve_sent: Callable[[Iterable[SentTranscript]], ResolvedSent],
    classes: FragmentClasses,
    files: PageFiles,
) -> tuple[TranscriptFragment, ...]:
    return FragmentPlan.read(events, resolve_sent=resolve_sent, classes=classes, files=files).fragments()


def transcript_file_readers(
    events: tuple[TranscriptEvent, ...],
    *,
    resolve_sent: Callable[[Iterable[SentTranscript]], ResolvedSent],
    classes: FragmentClasses,
) -> tuple[tuple[MessageReference, FileReader], ...]:
    """Every bus message these events draw once their sent reports resolve, with the read its
    files are listed under: what one page's file read asks before the page is drawn."""
    plan = FragmentPlan.read(events, resolve_sent=resolve_sent, classes=classes, files=NO_PAGE_FILES)
    return tuple((row.message.reference, row.file_reader)
                 for drawn in (*events, *plan.resolved.values())
                 for row in BUS_MESSAGE_ROW.project_value(drawn))
