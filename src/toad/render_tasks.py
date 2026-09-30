"""Typed, data-only renderer operations shared by local and persistent workers."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar, TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from agent_comms.transcript_events import TranscriptEvent, MarkdownTranscript
from agent_comms.mro_dispatch import MroDispatch, handles
from markdown_it.token import Token

from toad.markdown_preparation import PreparedMarkdown, prepare_tokens
from toad.widgets.patch_diff import PreparedPatch, prepare_patch
from toad.widgets.transcript_fragments import TranscriptFragment, transcript_fragments
from toad.rich_preparation import (
    PreparedRichContent,
    RichPresentation,
    RichSource,
    prepare_rich,
)

ResultT = TypeVar("ResultT", covariant=True)

if TYPE_CHECKING:
    from acp.schema import SessionNotification


class RenderExecution(ABC, Generic[ResultT]):
    @abstractmethod
    def execute(self) -> ResultT:
        """Execute pure preparation in the renderer process."""

    @abstractmethod
    def accept_result(self, result: object) -> ResultT:
        """Validate the result at a transport boundary."""



class RenderTask(RenderExecution[ResultT], DeclaredFamily, affix="RenderTask"):
    """A nominal operation with an exact input and result contract."""

    def reusable_inputs(self) -> object | None:
        """None means external state prevents sharing or retaining this capture."""
        return None

class ReusableRenderTask(RenderTask[ResultT]):
    def reusable_inputs(self) -> object:
        return self


class SessionUpdateValidation(DeclaredFamily, affix='SessionUpdateValidation'):
    @abstractmethod
    def publish(self, owner, session_id, raw, metadata): ...


@dataclass(frozen=True)
class AcceptedSessionUpdateValidation(SessionUpdateValidation):
    notification: SessionNotification

    def publish(self, owner, session_id, raw, metadata):
        owner.publish(session_id, self.notification)


@dataclass(frozen=True)
class RejectedSessionUpdateValidation(SessionUpdateValidation):
    error: str

    def publish(self, owner, session_id, raw, metadata):
        owner.reject(session_id, raw, metadata, self.error)


@dataclass(frozen=True)
class ValidateSessionUpdateTask(RenderTask[SessionUpdateValidation]):
    """Keep the official SDK's validator graph in process workers, not the UI."""

    session_id: str
    update: object
    metadata: dict | None = None

    def execute(self) -> SessionUpdateValidation:
        from toad.acp.sdk_boundary import decode_session_update

        try:
            notification = decode_session_update(self.session_id, self.update, self.metadata)
        except (ValueError, TypeError) as error:
            return RejectedSessionUpdateValidation(str(error))
        return AcceptedSessionUpdateValidation(notification)

    def accept_result(self, result: object) -> SessionUpdateValidation:
        if not isinstance(result, SessionUpdateValidation):
            raise TypeError("ACP validation worker returned an invalid result")
        return result


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
class MarkdownSyntaxRenderTask(ReusableRenderTask[list[Token]]):
    source: str

    def execute(self) -> list[Token]:
        from toad.conversation_markdown import parse_markdown_syntax
        return parse_markdown_syntax(self.source)

    async def prepare_body(self, renderer, ansi: bool, dark: bool) -> None:
        """Warm the same grammar and highlighted rows used by native delivery."""
        tokens = await renderer.submit(self)
        await renderer.submit(TokenRenderTask(tuple(tokens), ansi, dark))

    def accept_result(self, result: object) -> list[Token]:
        if not isinstance(result, list) or not all(isinstance(token, Token) for token in result):
            raise TypeError("Markdown syntax renderer returned invalid tokens")
        return result


@dataclass(frozen=True)
class TokenRenderTask(ReusableRenderTask[PreparedMarkdown]):
    tokens: tuple[Token, ...]
    ansi: bool
    dark: bool

    def execute(self) -> PreparedMarkdown:
        return prepare_tokens(list(self.tokens), self.ansi, self.dark)

    def accept_result(self, result: object) -> PreparedMarkdown:
        if not isinstance(result, PreparedMarkdown):
            raise TypeError("Token renderer returned an invalid result")
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
        await MarkdownSyntaxRenderTask(event.text).prepare_body(
            self.renderer, self.ansi, self.dark,
        )


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


def execute_render_task(task: RenderTask[ResultT]) -> ResultT:
    """Importable process entry point; transport adapters dispatch by task type."""
    return task.execute()
