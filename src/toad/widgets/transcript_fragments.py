"""Render-sized transcript fragments; wire records and cursors remain model-owned."""

from dataclasses import dataclass, replace
from collections.abc import Iterator
from typing import TYPE_CHECKING
from threading import local

from agent_comms import TranscriptEvent
from markdown_it import MarkdownIt

if TYPE_CHECKING:
    from toad.render_backend import Renderer

# Bound foreground work by input size, not by a timer after parsing has blocked.
FOREGROUND_CHARACTER_BUDGET = 8192
FOREGROUND_EVENT_BUDGET = 64


class _FragmentParserState(local):
    def __init__(self) -> None:
        self.parser = MarkdownIt("gfm-like")


_parser_state = _FragmentParserState()


def _fragment_parser() -> MarkdownIt:
    """Reuse parser machinery within one execution thread, never concurrently."""
    return _parser_state.parser


async def prepare_transcript_fragments(
    events: tuple[TranscriptEvent, ...], pool: "Renderer | None" = None,
) -> tuple["TranscriptFragment", ...]:
    """Prepare plain model data; never send widgets or application state to workers.

    Standalone Textual apps may not own a pool. Their large requests own and close
    a temporary pool, including on cancellation; there is no hidden global pool.
    """
    if (len(events) <= FOREGROUND_EVENT_BUDGET
            and sum(len(event.text) for event in events) <= FOREGROUND_CHARACTER_BUDGET):
        return transcript_fragments(events)
    from toad.render_tasks import TranscriptRenderTask

    if pool is not None:
        return await pool.submit(TranscriptRenderTask(events))
    from toad.render_processes import RenderProcessPool

    owned_pool = RenderProcessPool()
    try:
        return await owned_pool.submit(TranscriptRenderTask(events))
    finally:
        await owned_pool.aclose()


@dataclass(frozen=True)
class RenderBudget:
    characters: int = 800
    lines: int = 12

    def _split_table(self, text: str) -> Iterator[str]:
        """Page a large GFM table by rows, repeating its required header."""
        lines = text.splitlines(keepends=True)
        if len(lines) <= 2:
            yield text
            return
        header = "".join(lines[:2])
        rows: list[str] = []
        row_characters = 0
        row_limit = max(1, self.lines - 2)
        character_limit = max(self.characters, len(header) + 1)
        for row in lines[2:]:
            if rows and (
                len(rows) >= row_limit
                or len(header) + row_characters + len(row) > character_limit
            ):
                yield header + "".join(rows)
                rows = []
                row_characters = 0
            rows.append(row)
            row_characters += len(row)
        if rows:
            yield header + "".join(rows)

    def split(self, text: str) -> Iterator[str]:
        if not text:
            return
        if (len(text) <= self.characters
                and len(text.splitlines()) <= self.lines):
            # No block can exceed either budget when the entire document fits.
            # Return the unchanged source; there is no partition decision to
            # parse, and normal Markdown rendering still handles its syntax.
            yield text
            return
        lines = text.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))

        # Separate widgets always introduce a visual row boundary. Split only
        # between top-level Markdown blocks so rendering never invents a line
        # break at an arbitrary provider-chunk or character boundary.
        blocks = {
            token.map[0]: token.type
            for token in _fragment_parser().parse(text)
            if token.level == 0 and token.map is not None
        }
        starts = sorted({0, *blocks, len(lines)})
        parts: list[tuple[str, str | None]] = [
            (text[offsets[start] : offsets[stop]], blocks.get(start))
            for start, stop in zip(starts, starts[1:])
        ]
        pending = ""
        pending_lines = 0
        for part, kind in parts:
            if kind == "table_open" and (
                len(part) > self.characters or part.count("\n") > self.lines
            ):
                if pending:
                    yield pending
                    pending = ""
                    pending_lines = 0
                yield from self._split_table(part)
                continue
            part_lines = part.count("\n") + int(bool(part) and not part.endswith("\n"))
            exceeds = (
                pending
                and (
                    len(pending) + len(part) > self.characters
                    or pending_lines + part_lines > self.lines
                )
            )
            if exceeds:
                yield pending
                pending = ""
                pending_lines = 0
            pending += part
            pending_lines += part_lines
        if pending:
            yield pending


@dataclass(frozen=True)
class TranscriptFragment:
    events: tuple[TranscriptEvent, ...]


def transcript_fragments(events: tuple[TranscriptEvent, ...]) -> tuple[TranscriptFragment, ...]:
    fragments: list[TranscriptFragment] = []
    tools: dict[str, int] = {}
    budget = RenderBudget()
    for event in events:
        if event.kind in {"user", "assistant", "thinking", "notice", "sent"}:
            fragments.extend(
                TranscriptFragment((replace(event, text=part),)) for part in budget.split(event.text)
            )
        elif event.kind in {"tool_start", "tool_end"}:
            if event.tool_call_id in tools:
                index = tools[event.tool_call_id]
                fragments[index] = TranscriptFragment((*fragments[index].events, event))
            else:
                tools[event.tool_call_id] = len(fragments)
                fragments.append(TranscriptFragment((event,)))
    return tuple(fragments)
