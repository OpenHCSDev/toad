"""The history fragment model every frontend shares: a fragment's source, identity, what it
shows and its line blocks. Each frontend adds how it draws and measures those blocks."""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import ClassVar

from agent_comms.execution.turn_item import NativeItemId
from agent_comms.messaging.display_references import NoHistorySource
from agent_comms.messaging.historical_views import HistorySource
from agent_comms.messaging.message_page import MessagePage
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.messaging.messages import Message
from agent_comms.messaging.read_basis import DisplayIdentity, NoDisplaySelection
from agent_comms.messaging.sent_message import PublishedSentMessage
from agent_comms.nominal.field_codec import ToolCallId
from agent_comms.transcript.transcript_events import (
    IncomingTranscript,
    TextTranscript,
    TranscriptEvent,
)
from agent_comms.ui_model.message_category import MessageCategory
from formbridge.forms.declared_fields import DeclaredViews
from metaclass_registry.mro_dispatch import handles

from toad.client.line_blocks import (
    NO_LINK,
    Body,
    Divider,
    Gap,
    LineBlock,
    LineLink,
    LineRole,
    MutedRole,
    Span,
    Summary,
    ToggleDetails,
)
from toad.client.notification_status import (
    MessageQueueEntry,
    NotificationStatus,
    ShownFragment,
    UncheckedNotifications,
)
from toad.client.message_file_links import MessageFileLink, file_chips
from toad.client.structured_context import compact_preview
from toad.commit_claims import CommitClaim
from toad.core.projection import MroProjection
from toad.message_rows import MarkdownMessageStyle, MessageRow, WireMessageStyle


class CopiedText(MroProjection[str]):
    """What one event gives a copy of its fragment: its text, or nothing for an event without any."""

    @handles(TranscriptEvent)
    def nothing(self, event: TranscriptEvent) -> str:
        return ""

    @handles(TextTranscript)
    def text(self, event: TextTranscript) -> str:
        return event.text


COPIED_TEXT = CopiedText()


@dataclass(kw_only=True)
class GrowsInPlace:
    """A live block's fragment: one event that grows where it is, so its own counter, not
    its event count, says when the same fragment draws differently."""

    live_revision: int = 0

    @property
    def revision(self) -> int:
        return self.live_revision


@dataclass(frozen=True, kw_only=True)
class Shown(ShownFragment):
    """What a reader chose about one drawn fragment."""

    details_open: bool = False
    collapsed: bool = False

    def summary(self, title: str, role: type[LineRole], link: LineLink) -> Summary:
        """One clipped row whatever the title: state that arrives after layout
        (a notification answer) changes this text, never the fragment's height.
        The full text is behind the disclosure, which only the reader opens."""
        return Summary((Span(("▼ " if self.details_open else "▶ ") + title, role, link),))

    def toggled(self) -> Shown:
        return replace(self, details_open=not self.details_open)

    def toggled_collapsed(self) -> Shown:
        return replace(self, collapsed=not self.collapsed)


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

    @abstractmethod
    def file_blocks(self, links: tuple[MessageFileLink, ...]) -> tuple[LineBlock, ...]:
        """The chips of the message's files; only the part carrying its status draws them."""

    def draw_divider(self, consumer, divider: Divider) -> None:
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

    def draw_divider(self, consumer, divider: Divider) -> None:
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

    def file_blocks(self, links: tuple[MessageFileLink, ...]) -> tuple[LineBlock, ...]:
        return file_chips(links)


class InnerPart(PartPosition):
    __slots__ = ()
    has_details = False

    def notification_references(self, event: TranscriptEvent):
        return ()

    def status_blocks(self, shown: MessageShown, link: LineLink):
        return ()

    def outgoing_sources(self, publication: PublishedSentMessage):
        return ()

    def file_blocks(self, links: tuple[MessageFileLink, ...]) -> tuple[LineBlock, ...]:
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


@dataclass(frozen=True)
class FragmentCollapse(ToggleDetails):
    """A message header disclosure: collapses or expands all parts of one message."""

    touch_priority: ClassVar[int] = 0
    key: FragmentKey


class CursorRest:
    """Where a history's block cursor rests. This base is resting on no drawn message;
    a HistoryFragment is resting on that message."""

    # The messages the cursor owns while the history draws them.
    rested: tuple[HistoryFragment, ...] = ()
    # A drawn message is never maximized (a Textual widget block may be, through its cursor).
    allow_maximize: ClassVar[bool] = False

    @property
    def clipboard_text(self) -> str:
        return ""

    def expandable(self) -> bool:
        return False

    def expanded(self) -> bool:
        return False


@dataclass
class HistoryFragment(CursorRest):
    """One drawn part of a history's source: its events, identity, how it is shown and the
    line blocks it draws. A frontend's fragment adds how it lays out and paints them."""

    events: tuple[TranscriptEvent, ...]
    part_position: PartPosition = field(default_factory=OnlyPart, kw_only=True)
    starts_agent_activity: bool = False
    shown: Shown = field(default_factory=Shown, kw_only=True)
    # Core's page whose display evidence can mark this message read. Non-message
    # fragments (tool calls, context summaries, boundary markers) carry no such
    # evidence — None is the base default; `EvidencedFragment` overrides as a
    # required field. `HistoryReads.retain_painted` accepts whatever paints and
    # already skips the None case, so the row-painted call path works on any
    # subclass without a per-caller isinstance guard.
    evidence: MessagePage | None = field(default=None, kw_only=True)

    # Whether the fragment has details a reader can show and hide.
    has_details: ClassVar[bool] = False

    def header_collapse_link(self) -> FragmentCollapse | None:
        """Collapse link for this fragment's message header (including when pinned), or None."""
        return None

    def in_flow_collapse_link(self) -> FragmentCollapse | None:
        """Collapse link when this row itself draws the message's leading header divider."""
        return None

    @cached_property
    def revision(self):
        """What makes the same fragment draw differently, derived once from its events as its
        key and categories are: every row's cache key holds it, and Qt asks every loaded
        row's key on each layout (312,310 derivations in one scroll-back of 216 rows).

        A draft's ordered appends may fold into one text event, so its event count can stay
        one while the visible text grows.  The source text is already the drawing authority;
        carry it in the render key instead of inventing a second draft counter.  A live block
        that grows in place overrides this with its own counter.
        """
        return len(self.events), tuple(
            text for event in self.events if (text := COPIED_TEXT.project_value(event))
        )

    @property
    def body_text(self) -> str:
        """Plain-text body for copy / menu / long-press, empty for fragments that have no
        copyable body (tool-call title lines, context summaries). Overridden by
        `BusMessageHistoryFragment` to return its stored `text_part`; a future fragment
        kind with its own copy text overrides here instead of growing a getattr chain
        at the call site."""
        return ""

    def request_show(self, shown: Shown) -> bool:
        """Show the fragment so; whether that changed how it is shown."""
        if shown == self.shown:
            return False
        self.shown = shown
        return True

    @property
    def source_identity(self) -> EventSourceKey | ToolCallId:
        first = self.events[0]
        return EventSourceKey(type(first), self.arrival_position, first.ordinal)

    @cached_property
    def key(self) -> FragmentKey:
        return FragmentKey(self.source_identity, self.part_position.index)

    def message_head(self, fragments: Iterable[HistoryFragment]) -> HistoryFragment:
        """The first part of this fragment's message among ``fragments`` in order: where a
        tap on any of its parts brings the reader (both frontends' clicked-head reveal)."""
        return next((part for part in fragments if part.source_identity == self.source_identity), self)

    @property
    def pinned_dividers(self) -> tuple[Divider, ...]:
        """The header a top row in this fragment pins, and an arrival burst stacks: none for a
        fragment that draws no header."""
        return ()

    @property
    def details_link(self) -> FragmentDetails:
        return FragmentDetails(self.key)

    @property
    def collapse_link(self) -> FragmentCollapse:
        return FragmentCollapse(self.key)

    @property
    def arrival_position(self) -> int | NativeItemId:
        """The first event owns the fragment's stable source position."""
        return self.events[0].position

    def shown_live_by(self, claim: CommitClaim) -> bool:
        """Whether the live block that claim retires already showed this saved row."""
        return claim.repeats_native(self.events)

    @property
    def notification_references(self) -> tuple[MessageReference, ...]:
        return ()

    @property
    def sent_references(self) -> tuple[MessageReference, ...]:
        """The notifications of a message the reader sent; a composer's receipt follows them."""
        return ()

    @property
    def retained_bytes(self) -> int:
        """Only this fragment's record; the page owns events, a frontend adds what it keeps."""
        return 256

    @property
    def notification_identity(self) -> DisplayIdentity | NoDisplaySelection:
        return NoDisplaySelection()

    def queue_entries(self) -> tuple[MessageQueueEntry, ...]:
        return ()

    def draws(self, reference: MessageReference) -> bool:
        """Whether this fragment draws the bus message ``reference`` names; only bus-message
        fragments do."""
        return False

    @property
    def outgoing_sources(self):
        return ()

    @classmethod
    def capture_part(cls, event, text: str, **kwargs):
        return cls((replace(event, text=text),), **kwargs)

    @property
    def has_blocks(self) -> bool:
        """Fast O(1) check for whether this fragment draws any blocks in its current `shown`
        state; avoids rebuilding `line_blocks` inside hot layout/paint loops."""
        return True

    @property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        """What this fragment draws as shown now; `shown` is the one stored fact."""
        return self.blocks(self.shown)

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
    def rested(self) -> tuple[HistoryFragment, ...]:
        return (self,)

    def expandable(self) -> bool:
        return self.has_details and not self.shown.details_open

    def expanded(self) -> bool:
        return self.has_details and self.shown.details_open

    def shown_in(self, selected: frozenset[type[MessageCategory]]) -> bool:
        """A fragment shows when a filter selects any of its events' categories."""
        return not self.categories.isdisjoint(selected)

    @abstractmethod
    def blocks(self, shown: Shown) -> tuple[LineBlock, ...]:
        """What this fragment draws when shown so, one block per visual part; every frontend
        draws these same blocks."""


@dataclass(kw_only=True)
class MessageLines(HistoryFragment):
    """A bus message drawn as lines: what leads it, its text, the chips of the files it
    carries, then what trails it. `files` is what its page's read answered for it."""

    files: tuple[MessageFileLink, ...] = ()

    @property
    def leading(self) -> tuple[LineBlock, ...]:
        """Blocks above the message's own text."""
        return ()

    def leading_for(self, shown) -> tuple[LineBlock, ...]:
        """Blocks above the message's own text under ``shown``."""
        return self.leading

    @abstractmethod
    def text(self, shown) -> tuple[LineBlock, ...]:
        """The message's own text."""

    def trailing(self, shown) -> tuple[LineBlock, ...]:
        """Blocks below the message's own text and files."""
        return ()

    def blocks(self, shown):
        return (*self.leading_for(shown), *self.text(shown), *self.part_position.file_blocks(self.files),
                *self.trailing(shown))


@dataclass(kw_only=True)
class BusMessageHistoryFragment(MessageLines):
    """One bus-message builder: header, styled body and Core notification feedback."""

    shown: MessageShown = field(default_factory=MessageShown)
    text_part: str
    row: MessageRow
    notification_identity: DisplayIdentity | NoDisplaySelection = field(
        default=NoDisplaySelection(), repr=False, compare=False)

    @classmethod
    def capture_part(cls, event: TextTranscript, text: str, **kwargs):
        return cls((event,), text_part=text, **kwargs)

    @property
    def has_details(self) -> bool:
        return self.part_position.has_details

    @property
    def notification_references(self) -> tuple[MessageReference, ...]:
        return self.part_position.notification_references(self.events[0])

    @property
    def sent_references(self) -> tuple[MessageReference, ...]:
        return self.notification_references if self.row.outgoing else ()

    def queue_entries(self) -> tuple[MessageQueueEntry, ...]:
        return tuple(MessageQueueEntry(reference, self.shown.status)
                     for reference in self.notification_references)

    def draws(self, reference: MessageReference) -> bool:
        return self.events[0].source == reference

    def shown_live_by(self, claim: CommitClaim) -> bool:
        return claim.repeats_received(self.events)

    @property
    def clipboard_text(self):
        return self.shown.style.clipboard(self.row)

    def collapsible_header(self, shown: MessageShown) -> Divider:
        """This message's header divider with a tappable collapse/expand disclosure across
        the marker and non-linked divider chrome (preserving sender/target thread links)."""
        header = self.row.header
        marker = Span("▶ " if shown.collapsed else "▼ ", header.role, self.collapse_link)
        spans = tuple(
            replace(span, link=self.collapse_link) if span.link == NO_LINK else span
            for span in header.spans
        )
        return replace(header, spans=(marker, *spans))

    def header_collapse_link(self) -> FragmentCollapse | None:
        return self.collapse_link

    def in_flow_collapse_link(self) -> FragmentCollapse | None:
        return self.collapse_link if self.part_position.index == 0 else None

    @property
    def pinned_dividers(self) -> tuple[Divider, ...]:
        """The pinned sticky header keeps the same ▼/▶ collapse disclosure and sender/target
        links as the in-flow header so scrolling past the top never drops the disclosure arrow."""
        return (self.collapsible_header(self.shown),)

    @property
    def leading(self):
        return self.leading_for(self.shown)

    def leading_for(self, shown: MessageShown):
        return self.part_position.leading(self.collapsible_header(shown))

    @property
    def body_text(self):
        return self.text_part

    def text(self, shown):
        return shown.style.body(self.row, self.body_text)

    def trailing(self, shown):
        return self.part_position.status_blocks(shown, self.details_link)

    @property
    def has_blocks(self) -> bool:
        return not (self.shown.collapsed and self.part_position.index > 0)

    def blocks(self, shown: MessageShown):
        if shown.collapsed:
            if self.part_position.index > 0:
                return ()
            preview = compact_preview(self.row.message.body or self.body_text, 72)
            summary = (Summary((Span(preview, MutedRole, self.collapse_link),)),) if preview else ()
            return (*self.leading_for(shown), *summary)
        return super().blocks(shown)


@dataclass(kw_only=True)
class EvidencedFragment(DeclaredViews, MessageLines, ABC):
    """One wire message drawn as lines.

    `evidence` is Core's page whose display evidence can mark this message
    read; it is None when the page carried none and once the mark is written.
    """

    shown: MessageShown
    evidence: MessagePage | None
    checks_notifications: ClassVar[bool] = False

    @classmethod
    def of(cls, message: Message, *, reader: str, **fields) -> EvidencedFragment:
        """The fragment this frontend's family declares for the message's role: each frontend's
        root lists only its own members, so a role never picks another frontend's drawing."""
        return cls.showing(type(message.role).__mro__).from_message(message, reader=reader, **fields)

    @classmethod
    def from_message(cls, message, *, reader, page: MessagePage, **fields):
        return cls((IncomingTranscript.of(message, reader=reader),), **fields)

    @property
    def message(self) -> Message:
        return self.events[0].message

    @property
    def timestamp(self) -> float:
        return self.message.timestamp

    @property
    def clipboard_text(self) -> str:
        return self.message.body



class MembershipText(EvidencedFragment):
    """Someone joined or left: one muted line."""

    def text(self, shown: MessageShown):
        return (Body("— " + self.message.body, role=MutedRole),)


class HistoryLeading(MroProjection[tuple[LineBlock, ...]]):
    """A message an attached history recorded opens with where it came from; a live one with its header."""

    @handles(NoHistorySource)
    def live(self, source: NoHistorySource, fragment: WireMessage, header: tuple[LineBlock, ...],
             shown: MessageShown):
        return header

    @handles(HistorySource)
    def recorded(self, source: HistorySource, fragment: WireMessage, header: tuple[LineBlock, ...],
                 shown: MessageShown):
        message = fragment.message
        return (
            Gap(),
            Summary.titled(f"History · {source.original_root} · @{message.sender} created {message.sender_created_at}"),
            fragment.collapsible_header(shown),
        )


HISTORY_LEADING = HistoryLeading()


@dataclass(kw_only=True)
class WireMessage(BusMessageHistoryFragment, EvidencedFragment):
    """A sent message: its header, text and the state of its notifications."""

    @classmethod
    def from_message(cls, message, *, reader, page: MessagePage, **fields):
        return cls(
            (IncomingTranscript.of(message, reader=reader),),
            text_part=message.body,
            row=MessageRow(message, reader),
            notification_identity=page.selection.notification_identity,
            **fields,
        )

    @property
    def notification_references(self):
        return self.message.role.notification_references(self.message)

    def leading_for(self, shown: MessageShown):
        return HISTORY_LEADING.project_value(
            self.message.history_source, self, super().leading_for(shown), shown
        )
