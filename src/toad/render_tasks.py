"""Typed, data-only renderer operations shared by local and persistent workers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

from agent_comms import TranscriptEvent
from markdown_it.token import Token

from toad.markdown_preparation import PreparedMarkdown, prepare_markdown, prepare_tokens
from toad.widgets.patch_diff import PreparedPatch, prepare_patch
from toad.widgets.transcript_fragments import TranscriptFragment, transcript_fragments

ResultT = TypeVar("ResultT", covariant=True)


class RenderTask(ABC, Generic[ResultT]):
    """A nominal operation with an exact input and result contract."""

    @abstractmethod
    def execute(self) -> ResultT:
        """Execute pure preparation in the renderer process."""

    @abstractmethod
    def accept_result(self, result: object) -> ResultT:
        """Validate the result at a transport boundary."""


@dataclass(frozen=True)
class PatchRenderTask(RenderTask[PreparedPatch]):
    source: str
    ansi: bool
    dark: bool

    def execute(self) -> PreparedPatch:
        return prepare_patch(self.source, self.ansi, self.dark)

    def accept_result(self, result: object) -> PreparedPatch:
        if not isinstance(result, PreparedPatch):
            raise TypeError("Patch renderer returned an incompatible result")
        return result


@dataclass(frozen=True)
class MarkdownRenderTask(RenderTask[PreparedMarkdown]):
    source: str
    project: str
    ansi: bool
    dark: bool

    def execute(self) -> PreparedMarkdown:
        return prepare_markdown(self.source, self.project, self.ansi, self.dark)

    def accept_result(self, result: object) -> PreparedMarkdown:
        if not isinstance(result, PreparedMarkdown):
            raise TypeError("Markdown renderer returned an incompatible result")
        return result


@dataclass(frozen=True)
class TokenRenderTask(RenderTask[PreparedMarkdown]):
    tokens: tuple[Token, ...]
    ansi: bool
    dark: bool

    def execute(self) -> PreparedMarkdown:
        return prepare_tokens(list(self.tokens), self.ansi, self.dark)

    def accept_result(self, result: object) -> PreparedMarkdown:
        if not isinstance(result, PreparedMarkdown):
            raise TypeError("Token renderer returned an incompatible result")
        return result


@dataclass(frozen=True)
class TranscriptRenderTask(RenderTask[tuple[TranscriptFragment, ...]]):
    events: tuple[TranscriptEvent, ...]

    def execute(self) -> tuple[TranscriptFragment, ...]:
        return transcript_fragments(self.events)

    def accept_result(self, result: object) -> tuple[TranscriptFragment, ...]:
        if not isinstance(result, tuple) or not all(isinstance(item, TranscriptFragment) for item in result):
            raise TypeError("Transcript renderer returned an incompatible result")
        return result


type RendererTask = PatchRenderTask | MarkdownRenderTask | TokenRenderTask | TranscriptRenderTask
type RendererResult = PreparedPatch | PreparedMarkdown | tuple[TranscriptFragment, ...]


def execute_render_task(task: RenderTask[ResultT]) -> ResultT:
    """Importable process entry point; transport adapters dispatch by task type."""
    return task.execute()
