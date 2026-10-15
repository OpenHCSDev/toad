"""Render-sized transcript fragments; wire records and cursors remain model-owned."""

import asyncio
from dataclasses import dataclass, field, replace
from functools import cached_property
from collections.abc import Iterator
from typing import TYPE_CHECKING, ClassVar

from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.message_reference import MessageReference
from agent_comms.transcript_events import (
    AgentTextTranscript, ContextTranscript, IncomingTranscript, MarkdownTranscript, SentTranscript,
    TextTranscript, ThinkingTranscript, ToolTranscript, TranscriptEvent, UserTranscript,
)

from toad.line_blocks import (
    AgentRole, Body, Divider, Gap, LineBlock, LineRole, MutedRole, Summary, ToggleDetails, UserRole,
)
from toad.message_rows import MarkdownMessageStyle, MessageRow, WireMessageStyle
from toad.notification_status import NotificationStatus, UncheckedNotifications
from toad.menus import MenuItem
from toad.render_backend import ReusableRenderTask
from toad.markdown_preparation import PreparedMarkdownPart
from toad.acp.status import ToolCallStatus
from toad.widgets.agent_activity import AgentActivityBoundary, AgentActivityPresentation
from toad.widgets.message_filter import MessageCategory, event_category

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


class FragmentLineConsumer(MroDispatch):
    """Turn a fragment's events into line blocks, one handler per event family."""

    def __init__(self, *, show_divider: bool):
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
        self.blocks += [Body(event.text, bar=UserRole, markdown=False), Gap()]

    @handles(AgentTextTranscript)
    def agent(self, event: AgentTextTranscript) -> None:
        self.divider("Agent", event.timestamp, AgentRole)
        self.blocks += [Body(event.text), Gap()]

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


@dataclass
class TranscriptFragment:
    events: tuple[TranscriptEvent, ...]
    continuation: bool = False
    # The producer knows whether more pieces of this source text follow.
    continues: bool = field(default=False, kw_only=True)
    starts_agent_activity: bool = False
    shown: Shown = field(default_factory=Shown, kw_only=True)
    # Whether the fragment has details a reader can show and hide.
    has_details: ClassVar[bool] = False
    checks_notifications: ClassVar[bool] = False

    @property
    def notification_references(self) -> tuple[MessageReference, ...]:
        return ()

    def blocks(self, shown: Shown) -> tuple[LineBlock, ...]:
        """What this fragment draws in committed history when shown so, one block per visual part.

        A continuation of the previous fragment has no divider. The blocks do
        not depend on the width: each width's lines are built from them.
        """
        consumer = FragmentLineConsumer(show_divider=not self.continuation)
        if self.starts_agent_activity and not self.continuation:
            consumer.blocks.extend(AgentActivityPresentation.group)
        for event in self.events:
            consumer.dispatch_sync(event)
        return tuple(consumer.blocks)

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return self.blocks(self.shown)

    def show(self, shown: Shown) -> None:
        """Change the displayed state; its render request supplies any prepared lines."""
        self.shown = shown
        for held in ("line_blocks", "_lines", "_plain"):
            self.__dict__.pop(held, None)

    @cached_property
    def categories(self) -> frozenset[type[MessageCategory]]:
        """The message categories of this fragment's events, derived once."""
        return frozenset(map(event_category, self.events))

    @property
    def timestamp(self) -> float | None:
        """When this fragment's first event happened."""
        return self.events[0].timestamp

    @property
    def clipboard_text(self) -> str | None:
        """What copying this fragment gives: its text as written."""
        return "\n\n".join(event.text for event in self.events
                           if isinstance(event, TextTranscript)) or None

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

    def lines_for(self, width: int, theme):
        """Cached lookup is geometry-only; source changes use declared invalidation."""
        held = self.__dict__.get("_lines")
        return held[1] if held is not None and held[0].preparation.matches(width, theme) else None

    def invalidate_lines(self):
        self.__dict__.pop("_lines", None)

    def hold_lines(self, request, lines) -> None:
        """Retain the owning request, unless the fragment changed its source blocks."""
        if request.blocks is self.line_blocks:
            self._lines = request, lines

    def plain_lines(self, width: int, theme):
        """Plain wrapped lines drawn until styled lines arrive; one per width."""
        from toad.widgets.transcript_lines import PlainLines

        held = self.__dict__.get("_plain")
        if held is None or held[0] != theme or held[1].width != width:
            held = self.__dict__["_plain"] = theme, PlainLines(width, theme, self.line_blocks)
        return held[1]


    @cached_property
    def retained_bytes(self) -> int:
        """Worker-owned immutable input cost, never an acquisition graph."""
        from toad.work_preparation import retained_bytes

        return retained_bytes(self)


@dataclass(kw_only=True)
class ToolTranscriptFragment(TranscriptFragment):
    """One tool call with everything it reported: a title line, and its output when opened."""

    tool_call: ToolCallStatus
    output_parts: "tuple[ToolOutputPart, ...]"

    @property
    def has_details(self) -> bool:
        # A multiline title needs disclosure even before output arrives. Core's
        # sent-message output still does not become a second saved message.
        return AgentActivityPresentation.tool_has_details(
            self.tool_call, any(part.has_details for part in self.output_parts)
        )

    def blocks(self, shown):
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

    @cached_property
    def row(self) -> MessageRow:
        raise NotImplementedError

    @property
    def checks_notifications(self) -> bool:
        # One footer per original message, not one per Markdown piece.
        return not self.continues

    @property
    def has_details(self) -> bool:
        return self.checks_notifications

    @property
    def notification_references(self) -> tuple[MessageReference, ...]:
        return (self.events[0].source,)

    @property
    def block_menu(self):
        return self.row.menu

    @property
    def clipboard_text(self):
        return self.shown.style.clipboard(self.row)

    @property
    def leading(self):
        return () if self.continuation else (Gap(), self.row.header)

    def text(self, shown):
        return shown.style.body(self.row)

    def trailing(self, shown):
        return () if self.continues else shown.status.blocks(shown)

    def blocks(self, shown):
        return (*self.leading, *self.text(shown), *self.trailing(shown))


class IncomingMessageFragment(BusMessageFragment):
    @cached_property
    def row(self) -> MessageRow:
        return MessageRow.incoming(self.events[0])


class SentMessageFragment(BusMessageFragment):
    @cached_property
    def row(self) -> MessageRow:
        return MessageRow.sent(self.events[0])


class ContextTranscriptFragment(TranscriptFragment):
    """The coordination context an agent was given: one line, and its text when opened."""

    has_details = True

    def blocks(self, shown):
        summary = shown.summary("Agent coordination context")
        if not shown.details_open:
            return (summary,)
        return (summary, *(Body(event.text, role=MutedRole, bar=MutedRole, markdown=False)
                           for event in self.events))


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

    @handles(IncomingTranscript)
    def incoming(self, event: IncomingTranscript):
        self.text(event, IncomingMessageFragment)

    @handles(SentTranscript)
    def sent(self, event: SentTranscript):
        self.text(event, SentMessageFragment)

    @handles(UserTranscript, MarkdownTranscript)
    def text(self, event: TextTranscript, kind: type[TranscriptFragment] = TranscriptFragment):
        starts_activity = self.boundary.observe(event_category(event)) if event.starts_activity else False
        source = PreparedMarkdownPart.capture(event.text)
        parts = tuple(self.budget.split(source)) if self.split_text else (source,)
        self.fragments.extend(
            kind((replace(event, text=part.text),), continuation=self.continuation or index > 0,
                 continues=index < len(parts) - 1,
                 starts_agent_activity=starts_activity and index == 0)
            for index, part in enumerate(parts)
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
    events: tuple[TranscriptEvent, ...], *, continuation: bool = False, split_text: bool = True, scope=None,
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
            tool_call=call, output_parts=ToolOutput.capture_projection(call, scope),
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
