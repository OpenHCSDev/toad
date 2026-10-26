"""Render-sized transcript fragments; wire records and cursors remain model-owned."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from functools import cached_property, partial
from typing import TYPE_CHECKING, ClassVar

from agent_comms.field_codec import ToolCallId
from agent_comms.message_reference import MessageReference
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
    LineRole,
    MarkdownBody,
    MutedRole,
    Summary,
    ToggleDetails,
    UserRole,
)
from toad.markdown_preparation import PreparedMarkdownPart
from toad.menus import MenuItem
from toad.message_rows import MarkdownMessageStyle, MessageRow, WireMessageStyle
from toad.notification_status import NotificationStatus, UncheckedNotifications
from toad.widgets.agent_activity import AgentActivityPresentation
from toad.widgets.transcript_lines import AcquiredRows, NoRows, RowAcquisition

if TYPE_CHECKING:
    from agent_comms.messages import Message as BusMessage

    from toad.tool_output import ToolOutputPart
    from toad.widgets.committed_presentation import CommitClaim
    from toad.widgets.transcript_lines import (
        BlockLines,
        Lines,
        LineTheme,
        RichLineRenderer,
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
        blocks = {
            token.map[0]: (index, token.type)
            for index, token in enumerate(source.tokens)
            if token.level == 0 and token.map is not None
        }
        starts = sorted({0, *blocks, len(lines)})
        parts = [
            (
                start,
                stop,
                blocks.get(start, (0, None))[0],
                blocks.get(stop, (len(source.tokens), None))[0],
                blocks.get(start, (0, None))[1],
            )
            for start, stop in zip(starts, starts[1:])
        ]
        pending_first = 0
        pending_stop = 0
        pending_token_first = 0
        pending_token_stop = 0
        pending_characters = 0
        pending_lines = 0

        def select(first: int, stop: int, token_first: int, token_stop: int):
            return source.select_blocks(text[offsets[first] : offsets[stop]], first, slice(token_first, token_stop))

        for start, stop, token_first, token_stop, kind in parts:
            part = text[offsets[start] : offsets[stop]]
            if kind == "table_open" and (len(part) > self.characters or part.count("\n") > self.lines):
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

    def __init__(self, *, show_divider: bool) -> None:
        self.show_divider = show_divider
        self.blocks: list[LineBlock] = []

    def divider(self, label: str, timestamp: float | None, role: type[LineRole]) -> None:
        if self.show_divider:
            self.blocks.append(Divider.titled(label, role, timestamp))

    @handles(TranscriptEvent)
    def other(self, event: TranscriptEvent) -> None:
        """Events without visible text in committed history draw nothing."""

    @handles(UserTranscript)
    def user(self, event: UserTranscript) -> None:
        self.divider("User", event.timestamp, UserRole)
        self.blocks += [Body(event.text, bar=UserRole), Gap()]

    @handles(AgentTextTranscript)
    def agent(self, event: AgentTextTranscript) -> None:
        self.divider("Agent", event.timestamp, AgentRole)
        self.blocks += [MarkdownBody(event.text), Gap()]

    @handles(SentTranscript)
    def sent_report(self, event: SentTranscript) -> None:
        from toad.tool_output import SentMessageToolOutputPart

        self.blocks.extend(SentMessageToolOutputPart.capture(event).line_blocks)

    @handles(ThinkingTranscript)
    def thinking(self, event: ThinkingTranscript) -> None:
        if event.text.strip():
            self.blocks += AgentActivityPresentation.thinking(event.text)


@dataclass(frozen=True, kw_only=True)
class Shown:
    """What a reader chose about one drawn fragment."""

    details_open: bool = False

    def summary(self, title: str, role: type[LineRole] = MutedRole) -> Summary:
        """The line that names a fragment's details; clicking it shows or hides them."""
        return Summary.titled(("▼ " if self.details_open else "▶ ") + title, role, ToggleDetails())

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
    def status_blocks(self, shown: MessageShown) -> tuple[LineBlock, ...]: ...

    @abstractmethod
    def outgoing_sources(self, publication: PublishedSentMessage): ...


class LastPart(PartPosition):
    __slots__ = ()
    has_details = True

    def notification_references(self, event):
        return (event.source,)

    def status_blocks(self, shown: MessageShown):
        return shown.status.blocks(shown)

    def outgoing_sources(self, publication: PublishedSentMessage):
        return (publication.reference,)


class InnerPart(PartPosition):
    __slots__ = ()
    has_details = False

    def notification_references(self, event: TranscriptEvent):
        return ()

    def status_blocks(self, shown: MessageShown):
        return ()

    def outgoing_sources(self, publication: PublishedSentMessage):
        return ()


@dataclass(frozen=True)
class EventSourceKey:
    """One kind of transcript event at its recorded source position."""

    event_type: type[TranscriptEvent]
    position: int | NativeItemId


@dataclass(frozen=True)
class FragmentKey:
    """A source occurrence and its text part, unchanged by page serialization."""

    source: EventSourceKey | ToolCallId
    part: int


@dataclass
class TranscriptFragment:
    events: tuple[TranscriptEvent, ...]
    continuation: bool = False
    part_position: PartPosition = field(default_factory=LastPart, kw_only=True)
    starts_agent_activity: bool = False
    shown: Shown = field(default_factory=Shown, kw_only=True)
    # Whether the fragment has details a reader can show and hide.
    has_details: ClassVar[bool] = False

    @property
    def source_identity(self) -> EventSourceKey | ToolCallId:
        return EventSourceKey(type(self.events[0]), self.arrival_position)

    @cached_property
    def key(self) -> FragmentKey:
        return FragmentKey(self.source_identity, self.part_position.index)

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

    def draws(self, message: BusMessage) -> bool:
        """Whether this fragment draws that bus message; only bus-message fragments do."""
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

    def blocks(self, shown: Shown) -> tuple[LineBlock, ...]:
        """What this fragment draws in committed history when shown so, one block per visual part.

        A continuation of the previous fragment has no divider. The blocks do
        not depend on the width: each width's lines are built from them.
        """
        consumer = FragmentLineConsumer(show_divider=not self.continuation)
        if self.starts_agent_activity and not self.continuation:
            consumer.blocks.extend(AgentActivityPresentation.group)
        for event in self.events:
            consumer.project_value(event)
        return tuple(consumer.blocks)

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return self.blocks(self.shown)

    def show(self, shown: Shown) -> None:
        """Change the displayed state; its render request supplies any prepared lines."""
        self.shown = shown
        self.__dict__.pop("line_blocks", None)
        self.invalidate_lines()
        self._plain = NoRows()

    @cached_property
    def categories(self) -> frozenset[type[MessageCategory]]:
        """The message categories of this fragment's events, derived once."""
        return frozenset(event.category for event in self.events)

    @property
    def timestamp(self) -> float | None:
        """When this fragment's first event happened."""
        return self.events[0].timestamp

    @property
    def clipboard_text(self) -> str | None:
        """What copying this fragment gives: its text as written."""
        return "\n\n".join(event.text for event in self.events if isinstance(event, TextTranscript)) or None

    @property
    def block_menu(self) -> tuple[MenuItem, ...]:
        """What the cursor's menu offers on this fragment, besides copying."""
        return ()

    def shown_in(self, selected: frozenset[type[MessageCategory]]) -> bool:
        """A fragment shows when a filter selects any of its events' categories."""
        return not self.categories.isdisjoint(selected)

    @cached_property
    def link_place(self) -> int:
        """What tells this fragment's drawn links apart from equal links in other fragments."""
        from toad.widgets.transcript_lines import link_place

        return link_place()

    def lines_for(self, width: int, theme: LineTheme):
        """Cached lookup is geometry-only; source changes use declared invalidation."""
        return self._lines.for_view(width, theme)

    def retains_lines(self, lines: BlockLines, theme: LineTheme) -> bool:
        """Whether measured rows still belong to this source and palette.

        RowAcquisition.for_view owns wrapping those rows at the layout width.
        """
        return self._lines.retains(lines, theme) or self._plain.retains(lines, theme)

    def invalidate_lines(self) -> None:
        self._lines = NoRows()

    def hold_lines(self, request: TranscriptLinesRenderTask, lines: BlockLines) -> bool:
        """Report whether these rows were retained for the fragment's source."""
        if request.blocks is self.line_blocks:
            self._lines = AcquiredRows(request.preparation, lines)
            return True
        return False

    def plain_lines(self, width: int, renderer: RichLineRenderer):
        """Plain wrapped lines drawn until styled lines arrive; one per width."""
        self._plain = acquired = self._plain.plain(width, renderer, self.line_blocks)
        return acquired.lines

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
        )


@dataclass(kw_only=True)
class BusMessageFragment(TranscriptFragment):
    """One bus-message builder: header, styled body and Core notification feedback."""

    shown: MessageShown = field(default_factory=MessageShown)
    text_part: str
    row: MessageRow

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

    def draws(self, message: BusMessage) -> bool:
        return self.events[0].source == message.reference

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
        return () if self.continuation else (Gap(), self.row.header)

    @property
    def body_text(self):
        return self.text_part

    def text(self, shown):
        return shown.style.body(self.row, self.body_text)

    def trailing(self, shown):
        return self.part_position.status_blocks(shown) if self.notification_references else ()

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
        summary = shown.summary("Agent coordination context")
        if not shown.details_open:
            return (summary,)
        return (summary, *(Body(event.text, role=MutedRole, bar=MutedRole) for event in self.events))


class TranscriptFragmentConsumer(MroProjection[None]):
    def __init__(self) -> None:
        self.fragments: list[TranscriptFragment | None] = []
        self.tools: dict[str, tuple[int, list[ToolTranscript], bool]] = {}
        self.reported_messages: dict[int, SentTranscript] = {}
        self.budget = RenderBudget()
        self.boundary = AgentActivityBoundary()

    @handles(ContextTranscript)
    def context(self, event: ContextTranscript) -> None:
        # One lazy disclosure owns the full metadata source.
        self.fragments.append(ContextTranscriptFragment((event,)))

    @handles(IncomingTranscript)
    def incoming(self, event: IncomingTranscript) -> None:
        self.text(event, BusMessageFragment, row=MessageRow(event.message, event.reader))

    @handles(SentTranscript)
    def sent(self, event: SentTranscript) -> None:
        self.reported_messages[len(self.fragments)] = event
        self.fragments.append(TranscriptFragment((event,)))

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
        source = PreparedMarkdownPart.capture(event.text)
        parts = kind.text_parts(source, self.budget)
        self.fragments.extend(
            kind.capture_part(
                event,
                part.text,
                continuation=index > 0,
                part_position=LastPart(index=index) if index == len(parts) - 1 else InnerPart(index=index),
                starts_agent_activity=starts_activity and index == 0,
                **kwargs,
            )
            for index, part in enumerate(parts)
        )

    @handles(ToolTranscript)
    def tool(self, event: ToolTranscript) -> None:
        if event.tool_call_id not in self.tools:
            self.tools[event.tool_call_id] = (
                len(self.fragments),
                [],
                self.boundary.observe(event.category),
            )
            self.fragments.append(None)  # Reserve the call's original position.
        _, events, _ = self.tools[event.tool_call_id]
        events.append(event)


def transcript_fragments(
    events: tuple[TranscriptEvent, ...],
    *,
    resolve_sent: Callable[[Iterable[SentTranscript]], dict[int, SentTranscript | PublishedSentMessage]],
) -> tuple[TranscriptFragment, ...]:
    from toad.tool_output import ToolOutput

    consumer = TranscriptFragmentConsumer()
    for event in events:
        consumer.project_value(event)
    reports = list(consumer.reported_messages.values())
    tools = {}
    for index, pending, starts_activity in consumer.tools.values():
        tool_events = tuple(pending)
        call = ToolCallStatus.from_transcript(tool_events)
        parts = ToolOutput.capture_recorded(call, tool_events)
        reports.extend(message for part in parts for message in part.sent_reports)
        tools[index] = (tool_events, starts_activity, call, parts)
    resolved = resolve_sent(reports)
    builder = TranscriptFragmentConsumer()
    canonical = {}
    for index, report in consumer.reported_messages.items():
        start = len(builder.fragments)
        builder.project_value(resolved[id(report)])
        canonical[index] = tuple(builder.fragments[start:])
    fragments = []
    for index, source in enumerate(consumer.fragments):
        if index in canonical:
            fragments.extend(canonical[index])
        elif index in tools:
            tool_events, starts_activity, call, parts = tools[index]
            parts = call.project_output(
                parts,
                partial(ToolOutput.apply_sent, resolved=resolved),
            )
            fragments.append(
                ToolTranscriptFragment(
                    tool_events,
                    starts_agent_activity=starts_activity,
                    tool_call=call,
                    output_parts=parts,
                )
            )
        else:
            fragments.append(source)
    return tuple(fragments)
