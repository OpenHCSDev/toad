"""Typed, data-only renderer operations shared by local and persistent workers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TypeVar

from toad.render_backend import ReusableRenderTask
from agent_comms.transcript_events import TranscriptEvent, MarkdownTranscript
from agent_comms.mro_dispatch import MroDispatch, handles

from toad.markdown_preparation import PreparedMarkdown, prepare_tokens
from toad.session_tracker import OpenTab
from toad.sidebar_preparation import (
    PreparedTab, PreparedThreadRow, ThreadRowPresentation,
    prepare_tab, prepare_thread_presentation,
)
from toad.widgets.patch_diff import PreparedPatch, prepare_patch
from toad.widgets.transcript_fragments import TranscriptFragment, transcript_fragments
from toad.rich_preparation import (
    PreparedRichContent,
    RichPresentation,
    RichSource,
    prepare_rich,
)

ResultT = TypeVar("ResultT", covariant=True)


@dataclass(frozen=True)
class PatchRenderTask(ReusableRenderTask[PreparedPatch]):
    source: str
    ansi: bool
    dark: bool

    def execute(self) -> PreparedPatch:
        return prepare_patch(self.source, self.ansi, self.dark)

    def accept_result(self, result: object) -> PreparedPatch:
        if not isinstance(result, PreparedPatch):
            raise TypeError("Patch renderer returned an invalid result")
        return result


@dataclass(frozen=True)
class MarkdownRenderTask(ReusableRenderTask[PreparedMarkdown]):
    """Parse and highlight one detached body before its independent delivery."""

    source: str
    ansi: bool
    dark: bool

    def execute(self) -> PreparedMarkdown:
        from toad.conversation_markdown import parse_markdown_syntax

        return prepare_tokens(parse_markdown_syntax(self.source), self.ansi, self.dark)

    def accept_result(self, result: object) -> PreparedMarkdown:
        if not isinstance(result, PreparedMarkdown):
            raise TypeError("Markdown renderer returned an invalid result")
        return result


class TranscriptBodyPreparation(MroDispatch):
    """Pure body work for declared transcript cases, without native widgets."""

    def __init__(self, renderer, ansi: bool, dark: bool):
        self.renderer, self.ansi, self.dark = renderer, ansi, dark

    async def prepare_fragments(self, fragments, keep_going, *, batch_size: int) -> None:
        """Warm a bounded source range in shared workers, without native mounts.

        Reversal/retirement stops the next batch. Already admitted render work
        keeps its existing runtime custody and resource limits.
        """
        for first in range(0, len(fragments), batch_size):
            if not keep_going():
                return
            await asyncio.gather(*(self.dispatch(event)
                                   for fragment in fragments[first:first + batch_size]
                                   for event in fragment.events))

    @handles(TranscriptEvent)
    async def undisclosed(self, event: TranscriptEvent) -> None:
        # Metadata and tool disclosure contents retain their existing lazy
        # owners. A viewport prediction does not open those disclosures.
        pass

    @handles(MarkdownTranscript)
    async def markdown(self, event: MarkdownTranscript) -> None:
        await self.renderer.submit(MarkdownRenderTask(event.text, self.ansi, self.dark))


@dataclass(frozen=True)
class TranscriptRenderTask(ReusableRenderTask[tuple[TranscriptFragment, ...]]):
    events: tuple[TranscriptEvent, ...]

    def execute(self) -> tuple[TranscriptFragment, ...]:
        return transcript_fragments(self.events)

    def accept_result(self, result: object) -> tuple[TranscriptFragment, ...]:
        if not isinstance(result, tuple) or not all(isinstance(item, TranscriptFragment) for item in result):
            raise TypeError("Transcript renderer returned an invalid result")
        return result


@dataclass(frozen=True)
class RichRenderTask(ReusableRenderTask[PreparedRichContent]):
    source: RichSource
    presentation: RichPresentation

    def execute(self) -> PreparedRichContent:
        return prepare_rich(self.source, self.presentation)

    def accept_result(self, result: object) -> PreparedRichContent:
        if not isinstance(result, PreparedRichContent):
            raise TypeError("Rich renderer returned an invalid result")
        return result


@dataclass(frozen=True)
class ThreadRowsRenderTask(ReusableRenderTask[tuple[PreparedThreadRow, ...]]):
    """Render captured display inputs without transporting backend authorities."""

    rows: tuple[ThreadRowPresentation, ...]

    def execute(self) -> tuple[PreparedThreadRow, ...]:
        return tuple(prepare_thread_presentation(row) for row in self.rows)

    def accept_result(self, result: object) -> tuple[PreparedThreadRow, ...]:
        if not isinstance(result, tuple) or not all(isinstance(row, PreparedThreadRow) for row in result):
            raise TypeError("Thread row renderer returned an invalid result")
        return result


@dataclass(frozen=True)
class TabRosterRenderTask(ReusableRenderTask[tuple[PreparedTab, ...]]):
    """The same renderer prepares tab content under its existing admission bound."""

    tabs: tuple[OpenTab, ...]

    def execute(self) -> tuple[PreparedTab, ...]:
        return tuple(prepare_tab(tab) for tab in self.tabs)

    def accept_result(self, result: object) -> tuple[PreparedTab, ...]:
        if not isinstance(result, tuple) or not all(isinstance(tab, PreparedTab) for tab in result):
            raise TypeError("Tab renderer returned an invalid result")
        return result
