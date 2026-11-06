"""Render-sized transcript fragments; wire records and cursors remain model-owned."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from functools import cached_property, partial
from typing import TYPE_CHECKING, ClassVar

from agent_comms.nominal.field_codec import ToolCallId
from agent_comms.message_reference import MessageReference
from agent_comms.recorded_time import EventTime
from agent_comms.read_basis import DisplayIdentity, NoDisplaySelection
from agent_comms.turn_item import NativeItemId
from metaclass_registry.mro_dispatch import handles
from agent_comms.sent_message import PublishedSentMessage
from agent_comms.transcript_events import (
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
from agent_comms.transcript_sources import AssignedTranscriptSource
from agent_comms.ui_model.message_category import AgentActivityBoundary, MessageCategory

from toad.acp.status import ToolCallStatus
from toad.core.projection import MroProjection
from toad.line_blocks import (
    AgentRole,
    Body,
    Divider,
    Gap,
    LineBlock,
    LineLink,
    LineRole,
    MarkdownMessageBody,
    MessageBody,
    MutedRole,
    Span,
    Summary,
    ToggleDetails,
    UserRole,
)
from toad.markdown_preparation import PreparedMarkdownPart
from toad.menus import MenuCommand
from toad.message_rows import MarkdownMessageStyle, MessageRow, WireMessageStyle
from toad.notification_status import MessageQueueEntry, NotificationStatus, UncheckedNotifications
from toad.tool_output import SentMessageToolOutputPart, ToolOutput
from toad.widgets.agent_activity import AgentActivityPresentation
from toad.render_backend import ReusableRenderTask
from toad.widgets.transcript_lines import AcquiredRows, NoRows, RowAcquisition
from toad.widgets.presentation_window import UNPLACED, Unplaced

if TYPE_CHECKING:

    from toad.tool_output import ToolOutputPart
    from textual.widget import Widget

    from toad.block_navigation import FragmentBlockCursor
    from toad.widgets.committed_presentation import CommitClaim
    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_history import LineHistory
    from toad.widgets.transcript_history import LaidOut, RowChange
    from toad.widgets.transcript_lines import (
        BlockLines,
        Lines,
        LineTheme,
        TranscriptLinesRenderTask,
    )


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

        # Separate widgets always introduce a visual row boundary. Split only
        # between top-level Markdown blocks so rendering never invents a line
        # break at an arbitrary provider-chunk or character boundary.
        # Top-level blocks by their first line: markdown-it's own token map, read once.
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
        # The blocks up to and including a drawn header; a later part draws none.
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


class CopiedText(MroProjection[str]):
    """What one event gives a copy of its fragment: its text, or nothing for an event without any."""

    @handles(TranscriptEvent)
    def nothing(self, event: TranscriptEvent) -> str:
        return ""

    @handles(TextTranscript)
    def text(self, event: TextTranscript) -> str:
        return event.text


COPIED_TEXT = CopiedText()


@dataclass(frozen=True, kw_only=True)
class Shown:
    """What a reader chose about one drawn fragment."""

    details_open: bool = False

    def summary(self, title: str, role: type[LineRole], link: LineLink) -> Summary:
        """One clipped row whatever the title: state that arrives after layout
        (a notification answer) changes this text, never the fragment's height.
        The full text is behind the disclosure, which only the reader opens."""
        return Summary((Span(("▼ " if self.details_open else "▶ ") + title, role, link),))

    def toggled(self) -> "Shown":
        return replace(self, details_open=not self.details_open)


@dataclass(frozen=True, kw_only=True)
class MessageShown(Shown):
    """Style and Core's feedback for one bus message, in any conversation."""

    style: WireMessageStyle = field(default_factory=MarkdownMessageStyle)
    status: NotificationStatus = field(default_factory=UncheckedNotifications)


@dataclass(frozen=True, slots=True)
class PartPosition(ABC):
    # Ordinal within the source event, not another source-position counter.
    index: int = 0

    @property
    @abstractmethod
    def has_details(self) -> bool: ...

    @abstractmethod
    def notification_references(self, event: TranscriptEvent) -> tuple[MessageReference, ...]: ...

    @abstractmethod
    def status_blocks(self, shown: MessageShown, link: LineLink) -> tuple[LineBlock, ...]: ...

    @abstractmethod
    def outgoing_sources(self, publication: PublishedSentMessage): ...

    def draw_divider(self, consumer: FragmentLineConsumer, divider: Divider) -> None:
        """A message's first part draws its header; later parts draw none."""
        consumer.blocks.append(divider)
        consumer.header_end = consumer.header_end or len(consumer.blocks)

    def leading(self, header: Divider) -> tuple[LineBlock, ...]:
        return (Gap(), header)

    def starts_activity(self, observed: bool) -> bool:
        """Only a message's first part opens the agent activity it starts."""
        return observed

    @staticmethod
    def sequence(count: int) -> tuple[PartPosition, ...]:
        """The positions of a source split into `count` parts, head first and status-bearing last.

        An empty source has no parts and so no positions."""
        if count < 2:
            return (OnlyPart(index=0),)[:count]
        return (HeadInnerPart(index=0), *(LaterInnerPart(index=index) for index in range(1, count - 1)),
                LaterLastPart(index=count - 1))


class LaterPart(PartPosition):
    """A part after the first: the header was drawn above it, so it draws none and starts nothing."""

    __slots__ = ()

    def draw_divider(self, consumer: FragmentLineConsumer, divider: Divider) -> None:
        pass

    def leading(self, header: Divider) -> tuple[LineBlock, ...]:
        return ()

    def starts_activity(self, observed: bool) -> bool:
        return False


class LastPart(PartPosition):
    __slots__ = ()
    has_details = True

    def notification_references(self, event):
        return (event.source,)

    def status_blocks(self, shown: MessageShown, link: LineLink):
        return shown.status.blocks(shown, link)

    def outgoing_sources(self, publication: PublishedSentMessage):
        return (publication.reference,)


class InnerPart(PartPosition):
    __slots__ = ()
    has_details = False

    def notification_references(self, event: TranscriptEvent):
        return ()

    def status_blocks(self, shown: MessageShown, link: LineLink):
        return ()

    def outgoing_sources(self, publication: PublishedSentMessage):
        return ()


class OnlyPart(LastPart):
    """A message in one part: it draws the header and carries the status."""

    __slots__ = ()


class HeadInnerPart(InnerPart):
    __slots__ = ()


class LaterInnerPart(LaterPart, InnerPart):
    __slots__ = ()


class LaterLastPart(LaterPart, LastPart):
    __slots__ = ()


@dataclass(frozen=True)
class EventSourceKey:
    """One kind of transcript event at its recorded source position and its ordinal in that record.

    One record can hold several events of one kind at one position (a Pi reply's
    thinking parts around a tool call); Core numbers a record's events, so the
    ordinal tells them apart (TranscriptEvent.ordinal).
    """

    event_type: type[TranscriptEvent]
    position: int | NativeItemId
    ordinal: int


@dataclass(frozen=True)
class FragmentKey:
    """A source occurrence and its text part, unchanged by page serialization."""

    source: EventSourceKey | ToolCallId
    part: int


@dataclass(frozen=True)
class FragmentDetails(ToggleDetails):
    """A disclosure names its original source occurrence, never a pointer position."""

    key: FragmentKey


class CursorRest:
    """Where a history's block cursor rests. This base is resting on no drawn message;
    a TranscriptFragment is resting on that message."""

    # The messages the cursor owns while the history draws them.
    rested: tuple[TranscriptFragment, ...] = ()

    def drawn_in(self, history: LineHistory) -> CursorRest:
        """This rest while `history` draws it; no rest once it does not."""
        return self

    def selects(self, owner: Widget, history: LineHistory) -> bool:
        """Whether resting here selects `owner`: no rest selects nothing."""
        return False

    @property
    def clipboard_text(self) -> str:
        return ""

    @property
    def block_menu(self) -> tuple[MenuCommand, ...]:
        return ()

    def placement_in(self, history: LineHistory) -> Unplaced:
        """Where the screen shows the rest: nowhere, until a fragment is rested on."""
        return UNPLACED

    def expandable(self) -> bool:
        return False

    def expanded(self) -> bool:
        return False

    def show_in(self, history: LineHistory) -> None:
        """Scroll a keyboard move's rest into view; no rest has nothing to show."""

    def show_head(self, cursor: FragmentBlockCursor, window: HistoryWindow) -> None:
        """Scroll a clicked rest's message head into view."""


NO_REST = CursorRest()


@dataclass
class TranscriptFragment(CursorRest):
    events: tuple[TranscriptEvent, ...]
    part_position: PartPosition = field(default_factory=OnlyPart, kw_only=True)
    starts_agent_activity: bool = False
    shown: Shown = field(default_factory=Shown, kw_only=True)
    # Whether the fragment has details a reader can show and hide.
    has_details: ClassVar[bool] = False

    @property
    def source_identity(self) -> EventSourceKey | ToolCallId:
        first = self.events[0]
        return EventSourceKey(type(first), self.arrival_position, first.ordinal)

    @cached_property
    def key(self) -> FragmentKey:
        return FragmentKey(self.source_identity, self.part_position.index)

    @property
    def details_link(self) -> FragmentDetails:
        return FragmentDetails(self.key)

    @property
    def arrival_position(self) -> int | NativeItemId:
        """The first event owns the fragment's stable source position."""
        return self.events[0].position

    def shown_live_by(self, claim: CommitClaim) -> bool:
        """Whether the live block that claim retires already showed this saved row."""
        return claim.repeats_native(self)

    _lines: RowAcquisition = field(default_factory=NoRows, init=False, repr=False, compare=False)
    _plain: RowAcquisition = field(default_factory=NoRows, init=False, repr=False, compare=False)

    @property
    def notification_references(self) -> tuple[MessageReference, ...]:
        return ()

    @property
    def notification_identity(self) -> DisplayIdentity | NoDisplaySelection:
        return NoDisplaySelection()

    def queue_entries(self) -> tuple[MessageQueueEntry, ...]:
        return ()

    def draws(self, reference: MessageReference) -> bool:
        """Whether this fragment draws the bus message ``reference`` names; only bus-message
        fragments do."""
        return False

    @classmethod
    def text_parts(cls, source: PreparedMarkdownPart, budget: RenderBudget):
        return tuple(budget.split(source))

    @property
    def outgoing_sources(self):
        return ()

    @classmethod
    def capture_part(cls, event, text: str, **kwargs):
        return cls((replace(event, text=text),), **kwargs)

    def text_rows(self, lines: Lines) -> range:
        """The fragment's content occupies its drawn rows unless it owns a header."""
        return range(lines.height)

    def sticky_header(self, block: int, row: int) -> tuple[Divider, ...]:
        """The header to pin over the window's top row, which is `row` of block `block`: a user
        or agent message pins its divider once the divider's first row is above the top row,
        and a later part, which draws none, always pins it."""
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
        """What this fragment draws in committed history when shown so, one block per visual part.

        A later part of a message has no divider. The blocks do
        not depend on the width: each width's lines are built from them.
        """
        return tuple(self.consumed.blocks)

    @property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        """What this fragment draws as shown now; `shown` is the one stored fact."""
        return self.blocks(self.shown)

    def request_show(self, shown: Shown) -> bool:
        """Record intent and retire old acquisitions; the page retains its painted layout."""
        if shown == self.shown:
            return False
        self.shown = shown
        # The rows drawn now stand in until the new state's rows arrive: a
        # status change must not redraw the message as plain rows (another
        # wrap, another height) and then as styled rows again.
        self._plain = self._lines.standing_in_for(self._plain)
        self.invalidate_lines()
        return True

    @cached_property
    def categories(self) -> frozenset[type[MessageCategory]]:
        """The message categories of this fragment's events, derived once."""
        return frozenset(event.category for event in self.events)

    @property
    def timestamp(self) -> float:
        """When this fragment's first event happened."""
        return self.events[0].timestamp

    @property
    def clipboard_text(self) -> str:
        """What copying this fragment gives: its text as written."""
        return "\n\n".join(text for event in self.events if (text := COPIED_TEXT.project_value(event)))

    @property
    def block_menu(self) -> tuple[MenuCommand, ...]:
        """What the cursor's menu offers on this fragment, besides copying."""
        return ()

    @property
    def rested(self) -> tuple[TranscriptFragment, ...]:
        return (self,)

    def drawn_in(self, history: LineHistory) -> CursorRest:
        return self if history.draws_fragment(self) else NO_REST

    def selects(self, owner: Widget, history: LineHistory) -> bool:
        return owner is history

    def placement_in(self, history: LineHistory) -> Unplaced:
        return history.fragment_shown(self)

    def expandable(self) -> bool:
        return self.has_details and not self.shown.details_open

    def expanded(self) -> bool:
        return self.has_details and self.shown.details_open

    def show_in(self, history: LineHistory) -> None:
        history.show_fragment(self)

    def show_head(self, cursor: FragmentBlockCursor, window: HistoryWindow) -> None:
        cursor.block.run_worker(cursor.show_clicked_head(self, window), group="message-heading", exclusive=True)

    def shown_in(self, selected: frozenset[type[MessageCategory]]) -> bool:
        """A fragment shows when a filter selects any of its events' categories."""
        return not self.categories.isdisjoint(selected)

    @cached_property
    def link_place(self) -> int:
        """What tells this fragment's drawn links apart from equal links in other fragments."""
        from toad.widgets.transcript_lines import link_place

        return link_place()

    def lines_for(self, width: int, theme: LineTheme) -> BlockLines:
        """Cached lookup is geometry-only; source changes use declared invalidation."""
        return self._lines.for_view(width, theme)

    def retains_lines(self, lines: BlockLines, theme: LineTheme) -> bool:
        """Whether measured rows still belong to this source and palette.

        RowAcquisition.for_view owns wrapping those rows at the layout width.
        """
        return self._lines.retains(lines, theme) or self._plain.retains(lines, theme)

    def invalidate_lines(self) -> None:
        self._lines = NoRows()

    def row_change(self, row: LaidOut, width: int, theme: LineTheme) -> RowChange:
        """What this fragment's current lines ask of the page row they replace."""
        return self._lines.replacing(row, width, theme)

    def hold_lines(self, request: TranscriptLinesRenderTask, lines: BlockLines) -> bool:
        """Report whether these rows were retained for the fragment's source."""
        if request.blocks == self.line_blocks:
            self._lines = AcquiredRows(request.preparation, lines, request.context)
            return True
        return False

    def stand_in_lines(self, width: int, theme: LineTheme) -> BlockLines:
        """The styled rows drawn before a status change, rewrapped, until its new rows arrive.

        A fragment never styled has none (NoStyledLines): its height is its styled
        rows', so the page styles it before measuring rather than stating a plain height.
        """
        return self._plain.for_view(width, theme)

    @property
    def retained_bytes(self) -> int:
        """Only this fragment's record and acquired rows; the page owns events."""
        return 256 + self._lines.preparation.retained_bytes + self._plain.preparation.retained_bytes


@dataclass(kw_only=True)
class ToolTranscriptFragment(TranscriptFragment):
    """One tool call with everything it reported: a title line, and its output when opened."""

    events: tuple[ToolTranscript, ...] = field(kw_only=False)
    tool_call: ToolCallStatus
    output_parts: "tuple[ToolOutputPart, ...]"

    @property
    def source_identity(self) -> ToolCallId:
        return self.events[0].tool_call_id

    @property
    def has_details(self) -> bool:
        # A multiline title needs disclosure even before output arrives.
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
class BusMessageFragment(TranscriptFragment):
    """One bus-message builder: header, styled body and Core notification feedback."""

    shown: MessageShown = field(default_factory=MessageShown)
    text_part: str
    row: MessageRow
    notification_identity: DisplayIdentity | NoDisplaySelection = field(
        default=NoDisplaySelection(), repr=False, compare=False)

    @classmethod
    def capture_part(cls, event: TextTranscript, text: str, **kwargs):
        return cls((event,), text_part=text, **kwargs)

    @classmethod
    def text_parts(cls, source: PreparedMarkdownPart, budget: RenderBudget):
        # Even an empty bus message owns its header and notification footer.
        return super().text_parts(source, budget) or (source,)

    @property
    def has_details(self) -> bool:
        return self.part_position.has_details

    @property
    def notification_references(self) -> tuple[MessageReference, ...]:
        return self.part_position.notification_references(self.events[0])

    def queue_entries(self) -> tuple[MessageQueueEntry, ...]:
        return tuple(MessageQueueEntry(reference, self.shown.status)
                     for reference in self.notification_references)

    def draws(self, reference: MessageReference) -> bool:
        return self.events[0].source == reference

    def shown_live_by(self, claim: CommitClaim) -> bool:
        return claim.repeats_received(self)

    @property
    def block_menu(self):
        return self.row.menu

    @property
    def clipboard_text(self):
        return self.shown.style.clipboard(self.row)

    @property
    def leading(self):
        return self.part_position.leading(self.row.header)

    def sticky_header(self, block: int, row: int) -> tuple[Divider, ...]:
        """Every part of a message pins its header once the header's first row is above the top
        row, which is `row` of block `block`; a later part draws no header, so it always
        pins it."""
        return (self.row.header,) if (block, row) > (len(self.leading) - 1, 0) else ()

    @property
    def body_text(self):
        return self.text_part

    def text(self, shown):
        return shown.style.body(self.row, self.body_text)

    def trailing(self, shown):
        return self.part_position.status_blocks(shown, self.details_link)

    def blocks(self, shown):
        return (*self.leading, *self.text(shown), *self.trailing(shown))


@dataclass(kw_only=True)
class SentMessageFragment(BusMessageFragment):
    publication: PublishedSentMessage

    @property
    def outgoing_sources(self):
        return self.part_position.outgoing_sources(self.publication)

    def shown_live_by(self, claim: CommitClaim) -> bool:
        return claim.repeats_sent(self)


class ContextTranscriptFragment(TranscriptFragment):
    """The coordination context an agent was given: one line, and its text when opened."""

    has_details = True

    def blocks(self, shown):
        summary = shown.summary("Agent coordination context", MutedRole, self.details_link)
        if not shown.details_open:
            return (summary,)
        return (summary, *(Body(event.text, role=MutedRole, bar=MutedRole) for event in self.events))


type ResolvedSent = Mapping[SentTranscript, SentTranscript | PublishedSentMessage]


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

    def sent_reports(self) -> tuple[SentTranscript, ...]:
        return (self.report,)

    def fragments(self, resolved: ResolvedSent) -> tuple[TranscriptFragment, ...]:
        builder = TranscriptFragmentConsumer()
        builder.project_value(resolved[self.report])
        return builder.unresolved()


@dataclass(frozen=True)
class TextSlot(FragmentSlot):
    """A text event, parsed and split only when its fragments are asked for.

    Reading events stays cheap whatever their length, so a draft that is read again on every
    streamed chunk can leave the parse to the worker that styles it.
    """

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
        return (ToolTranscriptFragment(tuple(self.events), starts_agent_activity=self.starts_activity,
                                       tool_call=self.call, output_parts=parts),)

    def unresolved(self) -> tuple[TranscriptFragment, ...]:
        return self.fragments({})


class TranscriptFragmentConsumer(MroProjection[None]):
    def __init__(self) -> None:
        self.slots: list[FragmentSlot] = []
        self.tools: dict[str, ToolSlot] = {}
        self.budget = RenderBudget()
        self.boundary = AgentActivityBoundary()

    def unresolved(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for slot in self.slots for fragment in slot.unresolved())

    @handles(ContextTranscript)
    def context(self, event: ContextTranscript) -> None:
        # One lazy disclosure owns the full metadata source.
        self.slots.append(BuiltSlot(ContextTranscriptFragment((event,))))

    @handles(IncomingTranscript)
    def incoming(self, event: IncomingTranscript) -> None:
        self.text(event, BusMessageFragment, row=MessageRow(event.message, event.reader))

    @handles(SentTranscript)
    def sent(self, event: SentTranscript) -> None:
        self.slots.append(SentSlot(TranscriptFragment((event,)), event))

    @handles(PublishedSentMessage)
    def published(self, message: PublishedSentMessage) -> None:
        original = message.message.core_message(AssignedTranscriptSource.open(message.scope))
        self.text(
            message.message,
            SentMessageFragment,
            publication=message,
            row=MessageRow(original, message.scope.recipient.name),
        )

    @handles(UserTranscript, MarkdownTranscript)
    def text(self, event: TextTranscript, kind: type[TranscriptFragment] = TranscriptFragment, **kwargs) -> None:
        starts_activity = self.boundary.observe(event.category) if event.starts_activity else False
        self.slots.append(TextSlot(event, kind, self.budget, starts_activity, kwargs))

    @handles(ToolTranscript)
    def tool(self, event: ToolTranscript) -> None:
        if event.tool_call_id not in self.tools:
            # The call keeps the place of its first event.
            self.tools[event.tool_call_id] = slot = ToolSlot(self.boundary.observe(event.category))
            self.slots.append(slot)
        self.tools[event.tool_call_id].events.append(event)


def transcript_fragments(
    events: tuple[TranscriptEvent, ...],
    *,
    resolve_sent: Callable[[Iterable[SentTranscript]], ResolvedSent],
) -> tuple[TranscriptFragment, ...]:
    return FragmentPlan.read(events, resolve_sent=resolve_sent).fragments()


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
    ) -> FragmentPlan:
        consumer = TranscriptFragmentConsumer()
        for event in events:
            consumer.project_value(event)
        resolved = resolve_sent(report for slot in consumer.slots for report in slot.sent_reports())
        return cls(tuple(consumer.slots), resolved)

    def fragments(self) -> tuple[TranscriptFragment, ...]:
        return tuple(fragment for slot in self.slots for fragment in slot.fragments(self.resolved))


@dataclass(frozen=True)
class DraftBlocksRenderTask(ReusableRenderTask[tuple[LineBlock, ...]]):
    """A draft's source blocks: it grows with every chunk, so the worker parses it."""

    plan: FragmentPlan

    def result_size(self, result: tuple[LineBlock, ...]) -> int:
        return 64 + sum(block.retained_bytes for block in result)

    def execute(self) -> tuple[LineBlock, ...]:
        return tuple(block for fragment in self.plan.fragments() for block in fragment.line_blocks)
