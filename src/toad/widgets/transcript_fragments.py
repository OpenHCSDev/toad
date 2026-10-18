"""Render-sized transcript fragments; wire records and cursors remain model-owned."""

from dataclasses import dataclass, field, replace
from functools import cached_property, partial
from collections.abc import Iterator
from typing import TYPE_CHECKING, ClassVar

from agent_comms.mro_dispatch import handles
from toad.core.projection import MroProjection
from agent_comms.message_reference import MessageReference
from agent_comms.sent_message import PublishedSentMessage
from agent_comms.transcript_sources import AssignedTranscriptSource
from agent_comms.transcript_events import (
    AgentTextTranscript, ContextTranscript, IncomingTranscript, MarkdownTranscript, SentTranscript,
    TextTranscript, ThinkingTranscript, ToolTranscript, TranscriptEvent, UserTranscript,
)

from toad.line_blocks import (
    AgentRole, Body, MarkdownBody, Divider, Gap, LineBlock, LineRole, MutedRole, Summary, ToggleDetails, UserRole,
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
    from toad.tool_output import ToolOutputPart
    from toad.widgets.transcript_lines import PlainLines


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


class FragmentLineConsumer(MroProjection):
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
    _lines: ClassVar[tuple | None] = None
    _plain: ClassVar["PlainLines | None"] = None

    @property
    def notification_references(self) -> tuple[MessageReference, ...]:
        return ()

    @classmethod
    def text_parts(cls, source, budget):
        return tuple(budget.split(source))

    @property
    def outgoing_sources(self):
        return ()

    @classmethod
    def capture_part(cls, event, text, **kwargs):
        return cls((replace(event, text=text),), **kwargs)

    def text_rows(self, lines) -> range:
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
            consumer.dispatch_sync(event)
        return tuple(consumer.blocks)

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return self.blocks(self.shown)

    def show(self, shown: Shown) -> None:
        """Change the displayed state; its render request supplies any prepared lines."""
        self.shown = shown
        self.__dict__.pop("line_blocks", None)
        self.invalidate_lines()
        self._plain = None

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
        held = self._lines
        if held is not None and held[0].preparation.theme is theme:
            lines = held[1].rewrap(width)
            self._lines = held[0], lines
            return lines
        return None

    def retains_lines(self, lines, theme) -> bool:
        """Whether measured rows still belong to this source and palette.

        Their width belongs to the rows themselves. Offscreen geometry may
        retain that measured width until the viewport asks for another one.
        """
        held, plain = self._lines, self._plain
        return (held is not None and held[0].preparation.theme is theme
                and held[1].preparation is lines.preparation
                or plain is not None and plain.preparation.theme is theme
                and plain.preparation.blocks is lines.preparation.blocks)

    def invalidate_lines(self):
        self._lines = None

    def hold_lines(self, request, lines) -> bool:
        """Report whether these rows were retained for the fragment's source."""
        if request.blocks is self.line_blocks:
            self._lines = request, lines
            return True
        return False

    def plain_lines(self, width: int, renderer):
        """Plain wrapped lines drawn until styled lines arrive; one per width."""
        from toad.widgets.transcript_lines import PlainLines

        held = self._plain
        if held is None or held.preparation.theme is not renderer.theme:
            held = PlainLines(width, renderer, self.line_blocks)
        self._plain = held.rewrap(width)
        return self._plain


    @property
    def source_payload_bytes(self) -> int:
        return sum(256 + 4 * event.text_size for event in self.events)

    @property
    def retained_bytes(self) -> int:
        """Declared source payload plus rows actually acquired by this view."""
        return (256 + self.source_payload_bytes
                + (self._lines.preparation.retained_bytes if self._lines is not None else 0)
                + (self._plain.preparation.retained_bytes if self._plain is not None else 0))


@dataclass(kw_only=True)
class ToolTranscriptFragment(TranscriptFragment):
    """One tool call with everything it reported: a title line, and its output when opened."""

    tool_call: ToolCallStatus
    output_parts: "tuple[ToolOutputPart, ...]"

    @property
    def retained_bytes(self) -> int:
        return super().retained_bytes + sum(part.retained_bytes for part in self.output_parts)

    @property
    def has_details(self) -> bool:
        # A multiline title needs disclosure even before output arrives.
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
    text_part: str
    row: MessageRow

    @property
    def retained_bytes(self) -> int:
        return super().retained_bytes + 4 * len(self.text_part)

    @classmethod
    def capture_part(cls, event, text, **kwargs):
        return cls((event,), text_part=text, **kwargs)

    @classmethod
    def text_parts(cls, source, budget):
        # Even an empty bus message owns its header and notification footer.
        return super().text_parts(source, budget) or (source,)

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

    @property
    def body_text(self):
        return self.text_part

    def text(self, shown):
        return shown.style.body(self.row, self.body_text)

    def trailing(self, shown):
        return () if self.continues else shown.status.blocks(shown)

    def blocks(self, shown):
        return (*self.leading, *self.text(shown), *self.trailing(shown))


@dataclass(kw_only=True)
class SentMessageFragment(BusMessageFragment):
    publication: PublishedSentMessage

    @property
    def outgoing_sources(self):
        return () if self.continues else (self.publication.reference,)

class ContextTranscriptFragment(TranscriptFragment):
    """The coordination context an agent was given: one line, and its text when opened."""

    has_details = True

    def blocks(self, shown):
        summary = shown.summary("Agent coordination context")
        if not shown.details_open:
            return (summary,)
        return (summary, *(Body(event.text, role=MutedRole, bar=MutedRole)
                           for event in self.events))


class TranscriptFragmentConsumer(MroProjection):
    def __init__(self, *, continuation: bool = False, split_text: bool = True):
        self.fragments: list[TranscriptFragment] = []
        self.tools: dict[str, int] = {}
        self.reported_messages: dict[int, SentTranscript] = {}
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
        self.text(event, BusMessageFragment, row=MessageRow(event.message, event.reader))

    @handles(SentTranscript)
    def sent(self, event: SentTranscript):
        self.reported_messages[len(self.fragments)] = event
        self.fragments.append(TranscriptFragment((event,), continuation=self.continuation))

    @handles(PublishedSentMessage)
    def published(self, message: PublishedSentMessage):
        original = message.message.core_message(AssignedTranscriptSource.open(message.scope))
        self.text(message.message, SentMessageFragment, publication=message,
                  row=MessageRow(original, message.scope.recipient.name))

    @handles(UserTranscript, MarkdownTranscript)
    def text(self, event: TextTranscript, kind: type[TranscriptFragment] = TranscriptFragment, **kwargs):
        starts_activity = self.boundary.observe(event_category(event)) if event.starts_activity else False
        source = PreparedMarkdownPart.capture(event.text)
        parts = kind.text_parts(source, self.budget) if self.split_text else (source,)
        self.fragments.extend(
            kind.capture_part(event, part.text, continuation=self.continuation or index > 0,
                 continues=index < len(parts) - 1,
                 starts_agent_activity=starts_activity and index == 0, **kwargs)
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
    events: tuple[TranscriptEvent, ...], *, continuation: bool = False, split_text: bool = True,
    resolve_sent=lambda reports: dict(zip(map(id, reports), reports)),
) -> tuple[TranscriptFragment, ...]:
    from toad.tool_output import ToolOutput

    consumer = TranscriptFragmentConsumer(continuation=continuation, split_text=split_text)
    for event in events:
        consumer.dispatch_sync(event)
    reports = list(consumer.reported_messages.values())
    tools = frozenset(consumer.tools.values())
    for index in tools:
        source = consumer.fragments[index]
        call = ToolCallStatus.from_transcript(source.events)
        parts = ToolOutput.capture_recorded(call, source.events)
        reports.extend(message for part in parts for message in part.sent_reports)
        consumer.fragments[index] = ToolTranscriptFragment(
            source.events, continuation=source.continuation,
            starts_agent_activity=source.starts_agent_activity,
            tool_call=call, output_parts=parts,
        )
    resolved = resolve_sent(reports)
    builder = TranscriptFragmentConsumer(continuation=continuation, split_text=split_text)
    canonical = {}
    for index, report in consumer.reported_messages.items():
        start = len(builder.fragments)
        builder.dispatch_sync(resolved[id(report)])
        canonical[index] = tuple(builder.fragments[start:])
    fragments = []
    for index, source in enumerate(consumer.fragments):
        if index in canonical:
            fragments.extend(canonical[index])
        elif index in tools:
            parts = source.tool_call.project_output(
                source.output_parts, partial(ToolOutput.apply_sent, resolved=resolved),
            )
            fragments.append(replace(source, output_parts=parts))
        else:
            fragments.append(source)
    return tuple(fragments)


@dataclass(frozen=True)
class TranscriptRenderTask(ReusableRenderTask[tuple[TranscriptFragment, ...]]):
    events: tuple[TranscriptEvent, ...]
    continuation: bool = False

    def result_size(self, result: tuple[TranscriptFragment, ...]) -> int:
        return 64 + sum(fragment.retained_bytes for fragment in result)

    def execute(self) -> tuple[TranscriptFragment, ...]:
        return transcript_fragments(self.events, continuation=self.continuation)

    def accept_result(self, result: object) -> tuple[TranscriptFragment, ...]:
        if not isinstance(result, tuple) or not all(isinstance(item, TranscriptFragment) for item in result):
            raise TypeError("Transcript renderer returned an invalid result")
        return result
