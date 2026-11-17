"""Textual-flavored transcript fragments: the canonical neutral family in
`toad.client.transcript_fragments` plus Textual's row acquisition, cursor-rest behavior,
and the Consumer that builds Textual subclasses from a transcript event stream. Qt siblings
of the same canonical family live in `toad.qt.history`; both backends import the authority
from `client/`, this module adds only what Textual needs on top.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from functools import cached_property, partial
from typing import TYPE_CHECKING

from agent_comms.messaging.sent_message import PublishedSentMessage
from agent_comms.transcript.transcript_events import (
    ContextTranscript,
    IncomingTranscript,
    MarkdownTranscript,
    SentTranscript,
    TextTranscript,
    ToolTranscript,
    TranscriptEvent,
    UserTranscript,
)
from agent_comms.ui_model.message_category import AgentActivityBoundary
from metaclass_registry.mro_dispatch import handles

from toad.acp.status import ToolCallStatus
from toad.client.fragments import (
    CursorRest,
    PartPosition,
    Shown,
)
from toad.client.line_blocks import LineBlock
from toad.client.transcript_fragments import (
    BusMessageFragment as _BusMessageFragment,
    ContextTranscriptFragment as _ContextTranscriptFragment,
    FragmentLineConsumer,
    RenderBudget,
    SentMessageFragment as _SentMessageFragment,
    ToolTranscriptFragment as _ToolTranscriptFragment,
    TranscriptFragment as _TranscriptFragment,
)
from toad.core.projection import MroProjection
from toad.markdown_preparation import PreparedMarkdownPart
from toad.menus import MenuCommand
from toad.message_rows import MessageRow
from toad.render_backend import ReusableRenderTask
from toad.tool_output import ToolOutput, ToolOutputPart
from toad.widgets.presentation_window import UNPLACED, Unplaced
from toad.widgets.transcript_lines import (
    AcquiredRows,
    BlockLines,
    Lines,
    LineTheme,
    NoRows,
    RowAcquisition,
    TranscriptLinesRenderTask,
    link_place,
)


if TYPE_CHECKING:
    from textual.widget import Widget

    from toad.block_navigation import FragmentBlockCursor
    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.transcript_history import LaidOut, LineHistory, RowChange


class TextualCursorRest(CursorRest):
    """No rest in a Textual history: it draws nowhere, selects nothing and shows nothing."""

    def drawn_in(self, history: LineHistory) -> CursorRest:
        """This rest while `history` draws it; no rest once it does not."""
        return self

    def selects(self, owner: Widget, history: LineHistory) -> bool:
        """Whether resting here selects `owner`: no rest selects nothing."""
        return False

    @property
    def block_menu(self) -> tuple[MenuCommand, ...]:
        return ()

    def placement_in(self, history: LineHistory) -> Unplaced:
        """Where the screen shows the rest: nowhere, until a fragment is rested on."""
        return UNPLACED

    def show_in(self, history: LineHistory) -> None:
        """Scroll a keyboard move's rest into view; no rest has nothing to show."""

    def show_head(self, cursor: FragmentBlockCursor, window: HistoryWindow) -> None:
        """Scroll a clicked rest's message head into view."""


NO_REST = TextualCursorRest()


@dataclass
class TranscriptFragment(_TranscriptFragment, TextualCursorRest):
    """A history fragment drawn by Textual: the canonical blocks derivation plus the row
    acquisition and cursor-rest behavior Textual's draw path needs. Qt's sibling uses the
    canonical class directly; this subclass exists only for what Textual adds."""

    _lines: RowAcquisition = field(default_factory=NoRows, init=False, repr=False, compare=False)

    _plain: RowAcquisition = field(default_factory=NoRows, init=False, repr=False, compare=False)

    def text_rows(self, lines: Lines) -> range:
        """The fragment's content occupies its drawn rows unless it owns a header."""
        return range(lines.height)

    def request_show(self, shown: Shown) -> bool:
        """Record intent and retire old acquisitions; the page retains its painted layout."""
        if not super().request_show(shown):
            return False
        # The rows drawn now stand in until the new state's rows arrive: a
        # status change must not redraw the message as plain rows (another
        # wrap, another height) and then as styled rows again.
        self._plain = self._lines.standing_in_for(self._plain)
        self.invalidate_lines()
        return True

    def drawn_in(self, history: LineHistory) -> CursorRest:
        return self if history.draws_fragment(self) else NO_REST

    def selects(self, owner: Widget, history: LineHistory) -> bool:
        return owner is history

    def placement_in(self, history: LineHistory) -> Unplaced:
        return history.fragment_shown(self)

    def show_in(self, history: LineHistory) -> None:
        history.show_fragment(self)

    def show_head(self, cursor: FragmentBlockCursor, window: HistoryWindow) -> None:
        cursor.block.run_worker(cursor.show_clicked_head(self, window), group="message-heading", exclusive=True)

    @cached_property
    def link_place(self) -> int:
        """What tells this fragment's drawn links apart from equal links in other fragments."""
        return link_place()

    def lines_for(self, width: int, theme: LineTheme) -> BlockLines:
        """Cached lookup is geometry-only; source changes use declared invalidation."""
        return self._lines.for_view(width, theme)

    def retains_lines(self, lines: BlockLines, theme: LineTheme) -> bool:
        """Whether measured rows still belong to this source and palette."""
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
        """The styled rows drawn before a status change, rewrapped, until its new rows arrive."""
        return self._plain.for_view(width, theme)

    @property
    def retained_bytes(self) -> int:
        """This fragment's record and its acquired rows; the page owns events."""
        return super().retained_bytes + self._lines.preparation.retained_bytes + self._plain.preparation.retained_bytes


@dataclass(kw_only=True)
class ToolTranscriptFragment(_ToolTranscriptFragment, TranscriptFragment):
    """One tool call drawn by Textual: the canonical tool blocks derivation plus row acquisition."""


@dataclass(kw_only=True)
class BusMessageFragment(_BusMessageFragment, TranscriptFragment):
    """A bus message drawn by Textual."""


@dataclass(kw_only=True)
class SentMessageFragment(_SentMessageFragment, BusMessageFragment):
    """A sent bus message drawn by Textual."""


class ContextTranscriptFragment(_ContextTranscriptFragment, TranscriptFragment):
    """The coordination context an agent was given, drawn by Textual."""


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
    """Build the Textual-flavored family from a stream of transcript events. Qt builds its own
    siblings from `toad.client.transcript_fragments` through a sibling consumer."""

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
        original = message.original
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
