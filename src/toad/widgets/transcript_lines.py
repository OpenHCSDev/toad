"""Committed transcript fragments drawn as prepared terminal lines.

A fragment's events become a few line blocks on the UI thread (cheap). The
render worker processes turn blocks into styled lines at a width; until those
arrive the same blocks draw as plain wrapped text, so a row is never blank.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import io

from rich.segment import Segment
from rich.style import Style

from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.transcript_events import (
    AgentTextTranscript, ContextTranscript, IncomingTranscript, SentTranscript,
    ThinkingTranscript, ToolTranscript, TranscriptEvent, UserTranscript,
)
from toad.render_backend import ReusableRenderTask

Row = tuple[Segment, ...]


@dataclass(frozen=True)
class LineStyles:
    """Theme colors for transcript lines, read once from the App's theme."""

    text: Style
    muted: Style
    user: Style
    agent: Style
    incoming: Style
    outgoing: Style
    notice: Style

    @classmethod
    def from_app(cls, app) -> LineStyles:
        from textual.color import Color

        theme = app.current_theme
        variables = app.theme_variables
        foreground = Color.parse(variables["foreground"])
        background = Color.parse(variables["background"])

        def style(value: str | None, fallback: Color = foreground) -> Style:
            return Style(color=(Color.parse(value) if value else fallback).rich_color)

        return cls(
            text=style(None),
            # Textual's text-muted is the foreground at 60% over the background.
            muted=Style(color=background.blend(foreground, 0.6).rich_color),
            user=style(theme.primary), agent=style(theme.secondary or theme.primary),
            incoming=style(theme.accent), outgoing=style(theme.success),
            notice=style(theme.warning),
        )


class LineBlock(ABC):
    """One visual part of a fragment; owns its styled and plain rendering."""

    @abstractmethod
    def rows(self, width: int) -> list[Row]:
        """Styled rows; runs in a render worker process."""

    def plain_rows(self, width: int) -> list[Row]:
        """Rows drawn before the styled rows arrive."""
        return self.rows(width)


def _fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


@dataclass(frozen=True)
class Divider(LineBlock):
    label: str
    style: Style

    def rows(self, width: int) -> list[Row]:
        label = f" {_fit(self.label, max(0, width - 8))} "
        left = max(0, (width - len(label)) // 2)
        right = max(0, width - left - len(label))
        return [(Segment("─" * left, self.style), Segment(label, self.style + Style(bold=True)),
                 Segment("─" * right, self.style))]


@dataclass(frozen=True)
class Summary(LineBlock):
    """A single collapsed line, such as a tool call or coordination context."""

    text: str
    style: Style

    def rows(self, width: int) -> list[Row]:
        return [(Segment(_fit(self.text, width), self.style),)]


@dataclass(frozen=True)
class Gap(LineBlock):
    def rows(self, width: int) -> list[Row]:
        return [()]


@dataclass(frozen=True)
class Body(LineBlock):
    """Message text, optionally behind a colored bar; Markdown when styled."""

    text: str
    style: Style
    bar: Style | None = None
    markdown: bool = True

    @property
    def inset(self) -> int:
        return 2 if self.bar is not None else 0

    def _with_bar(self, rows: list[Row]) -> list[Row]:
        if self.bar is None:
            return rows
        prefix = Segment("▌ ", self.bar)
        return [(prefix, *row) for row in rows]

    def rows(self, width: int) -> list[Row]:
        if not self.markdown:
            return self.plain_rows(width)
        from rich.console import Console
        from rich.markdown import Markdown

        inner = max(1, width - self.inset)
        console = Console(width=inner, color_system="truecolor", force_terminal=True,
                          file=io.StringIO(), legacy_windows=False)
        lines = console.render_lines(Markdown(self.text), console.options.update(width=inner),
                                     style=self.style, pad=False)
        return self._with_bar([tuple(line) for line in lines])

    def plain_rows(self, width: int) -> list[Row]:
        inner = max(1, width - self.inset)
        rows: list[Row] = []
        for line in self.text.splitlines() or [""]:
            line = line.expandtabs(4)
            for start in range(0, max(1, len(line)), inner):
                rows.append((Segment(line[start:start + inner], self.style),))
        return self._with_bar(rows)


def _clock(timestamp: float | None) -> str:
    from toad.widgets.message_divider import MessageClock

    return MessageClock.recorded(timestamp).display()[0] if timestamp is not None else ""


def _label(role: str, timestamp: float | None) -> str:
    clock = _clock(timestamp)
    return f"{role} · {clock}" if clock else role


class FragmentLineConsumer(MroDispatch):
    """Turn a fragment's events into line blocks, one handler per event family."""

    def __init__(self, styles: LineStyles, *, show_divider: bool):
        self.styles = styles
        self.show_divider = show_divider
        self.blocks: list[LineBlock] = []

    def divider(self, role: str, timestamp: float | None, style: Style) -> None:
        if self.show_divider:
            self.blocks.append(Divider(_label(role, timestamp), style))

    @handles(TranscriptEvent)
    def other(self, event: TranscriptEvent) -> None:
        """Events without visible text in committed history draw nothing."""

    @handles(UserTranscript)
    def user(self, event: UserTranscript) -> None:
        self.divider("User", event.timestamp, self.styles.user)
        self.blocks.append(Body(event.text, self.styles.text, bar=self.styles.user, markdown=False))
        self.blocks.append(Gap())

    @handles(AgentTextTranscript)
    def agent(self, event: AgentTextTranscript) -> None:
        self.divider("Agent", event.timestamp, self.styles.agent)
        self.blocks.append(Body(event.text, self.styles.text))
        self.blocks.append(Gap())

    @handles(ThinkingTranscript)
    def thinking(self, event: ThinkingTranscript) -> None:
        if event.text.strip():
            self.blocks.append(Body(event.text, self.styles.muted + Style(italic=True)))
            self.blocks.append(Gap())

    @handles(IncomingTranscript)
    def incoming(self, event: IncomingTranscript) -> None:
        route = event.route
        targets = ", ".join(route.targets) if route.targets else ""
        self.divider(f"{route.sender} → {targets}" if targets else route.sender,
                     event.timestamp, self.styles.incoming)
        self.blocks.append(Body(event.text, self.styles.text, bar=self.styles.incoming))
        self.blocks.append(Gap())

    @handles(SentTranscript)
    def sent(self, event: SentTranscript) -> None:
        reply = event.routing.reply if event.routing is not None else None
        targets = ", ".join(reply.targets) if reply is not None else ""
        self.divider(f"Sent → {targets}" if targets else "Sent", event.timestamp, self.styles.outgoing)
        self.blocks.append(Body(event.text, self.styles.text, bar=self.styles.outgoing))
        self.blocks.append(Gap())

    @handles(ContextTranscript)
    def context(self, event: ContextTranscript) -> None:
        self.blocks.append(Summary("▶ Agent coordination context", self.styles.muted))

    @handles(ToolTranscript)
    def tool(self, event: ToolTranscript) -> None:
        self.blocks.append(Summary(f"▶ {event.tool_name}", self.styles.muted))


@dataclass(frozen=True)
class PreparedLines:
    """Styled rows of one fragment at one width."""

    width: int
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class TranscriptLinesRenderTask(ReusableRenderTask[PreparedLines]):
    """Render a fragment's line blocks at a width in a render worker."""

    blocks: tuple[LineBlock, ...]
    width: int

    def execute(self) -> PreparedLines:
        return PreparedLines(self.width, tuple(row for block in self.blocks for row in block.rows(self.width)))

    def accept_result(self, result: object) -> PreparedLines:
        if not isinstance(result, PreparedLines) or result.width != self.width:
            raise TypeError("Transcript line renderer returned rows for a different width")
        return result
