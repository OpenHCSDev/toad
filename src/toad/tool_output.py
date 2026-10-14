"""Decoded tool output owns its presentation and preparation lifetime.

ACP dictionaries end at ``decode_content``. Presentation cases and the mounted
output owner operate on captured values, including when an adapter mutates an
earlier dictionary or changes Read's filename without changing its text.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import PurePath
import re
from weakref import ref

from agent_comms.declared_family import DeclaredFamily
from agent_comms.transcript_events import SentTranscript
from textual.await_complete import AwaitComplete
from textual.content import Content

from acp import schema
from agent_comms.mro_dispatch import MroDispatch, handles
from toad.line_blocks import Body, LineBlock, MutedRole, ToolOutputRole
from toad.message_rows import MarkdownMessageStyle, MessageRow
from toad.rich_preparation import AnsiContentSource, ContentSource, NativeContentSource


class ToolDetails(ABC):
    """A tool output part's only rendered details contract."""

    @abstractmethod
    def line_blocks(self) -> tuple[LineBlock, ...]: ...


class ToolOutputPart(ToolDetails, DeclaredFamily, affix="ToolOutputPart"):
    """A captured output value; each case owns its semantic detail blocks."""

    def permission_preview(self) -> ToolOutputPart | None:
        """Permission previews admit only text and file diffs."""
        return None

    @property
    def preview_dimensions(self) -> tuple[int, int] | None:
        return None


@dataclass(frozen=True)
class TextToolOutputPart(ToolOutputPart):
    text: str

    def permission_preview(self) -> ToolOutputPart:
        # Permission questions interpret all text as Markdown, independent of
        # the streaming output's Read/ANSI/literal heuristics.
        return MarkdownToolOutputPart(self.text)

    @classmethod
    @abstractmethod
    def accepts(cls, text: str, read_path: str | None) -> bool: ...

    @classmethod
    def from_text(cls, text: str, read_path: str | None) -> TextToolOutputPart:
        # Text presentation is not prescribed by ACP. The member owns its
        # heuristic, and new cases never add a second consumer inventory.
        candidates = [member for member in cls.members_with(SpecificTextToolOutputPart)
                      if member.accepts(text, read_path)] or [
                          member for member in cls.members_with(LiteralTextToolOutputPart)
                          if member.accepts(text, read_path)
                      ]
        if len(candidates) != 1:
            raise ValueError("Tool text requires exactly one presentation owner")
        return candidates[0].capture(text, read_path)

    @classmethod
    def capture(cls, text: str, read_path: str | None) -> TextToolOutputPart:
        return cls(text)


class SpecificTextToolOutputPart(TextToolOutputPart):
    """An attested Read/ANSI/Markdown interpretation takes precedence."""


class LiteralTextToolOutputPart(TextToolOutputPart):
    """The remaining text is literal; member order is never priority."""


class RetainedTextToolOutputPart(TextToolOutputPart):
    @property
    @abstractmethod
    def render_source(self) -> NativeContentSource: ...

    def line_blocks(self) -> tuple[LineBlock, ...]:
        return (Body(self.render_source.materialize().plain, role=ToolOutputRole,
                     bar=MutedRole, markdown=False),)


class PlainTextToolOutputPart(RetainedTextToolOutputPart, LiteralTextToolOutputPart):
    @classmethod
    def accepts(cls, text: str, read_path: str | None) -> bool:
        return read_path is None

    @property
    def render_source(self) -> NativeContentSource:
        return ContentSource(Content(self.text))


class AnsiTextToolOutputPart(RetainedTextToolOutputPart, SpecificTextToolOutputPart):
    @classmethod
    def accepts(cls, text: str, read_path: str | None) -> bool:
        return read_path is None and "\x1b" in text

    @property
    def render_source(self) -> NativeContentSource:
        return AnsiContentSource(self.text)


class MarkdownToolOutputPart(SpecificTextToolOutputPart):
    @classmethod
    def accepts(cls, text: str, read_path: str | None) -> bool:
        return read_path is None and "\x1b" not in text and (
            "```" in text or re.search(r"^#{1,6}\s.*$", text, re.MULTILINE) is not None
        )

    def line_blocks(self) -> tuple[LineBlock, ...]:
        return (Body(self.text, role=ToolOutputRole, bar=MutedRole),)


@dataclass(frozen=True)
class ReadToolOutputPart(SpecificTextToolOutputPart):
    path: str

    @classmethod
    def accepts(cls, text: str, read_path: str | None) -> bool:
        return read_path is not None

    @classmethod
    def capture(cls, text: str, read_path: str | None) -> ReadToolOutputPart:
        assert read_path is not None
        return cls(text, read_path)

    def line_blocks(self) -> tuple[LineBlock, ...]:
        return (Body.code(self.text, PurePath(self.path).suffix.removeprefix("."), bar=MutedRole),)


@dataclass(frozen=True)
class PatchToolOutputPart(ToolOutputPart):
    source: str

    def line_blocks(self) -> tuple[LineBlock, ...]:
        return (Body.code(self.source, "diff", bar=MutedRole),)

    @property
    def preview_dimensions(self) -> tuple[int, int]:
        return len(self.source), self.source.count("\n")


@dataclass
class SentMessageToolOutputPart(ToolOutputPart):
    """Render the send owner's original publication through semantic rows."""

    message: SentTranscript

    def line_blocks(self) -> tuple[LineBlock, ...]:
        row = MessageRow.sent(self.message)
        return (row.header, *MarkdownMessageStyle().body(row))


@dataclass(frozen=True)
class FileDiffToolOutputPart(ToolOutputPart):
    path: str
    old_text: str | None
    new_text: str

    def permission_preview(self) -> ToolOutputPart:
        return self

    def line_blocks(self) -> tuple[LineBlock, ...]:
        lines = unified_diff((self.old_text or "").splitlines(), self.new_text.splitlines(),
                             self.path, self.path, lineterm="")
        return (Body.code("\n".join(lines), "diff", bar=MutedRole),)


@dataclass(frozen=True)
class UnrenderedToolOutputPart(ToolOutputPart):
    """ACP media without a text projection has no rendered details."""

    source: object

    def line_blocks(self) -> tuple[LineBlock, ...]:
        return ()


@dataclass(frozen=True)
class TerminalToolOutputPart(ToolOutputPart):
    """ACP terminal output is projected by its existing terminal owner."""

    terminal_id: str

    def line_blocks(self) -> tuple[LineBlock, ...]:
        return ()


class ToolContentDecoder(MroDispatch):
    def __init__(self, read_path=None):
        self.read_path = read_path
        self.part = None

    @handles(schema.ContentToolCallContent)
    def content(self, item):
        self.dispatch_sync(item.content)

    @handles(schema.TextContentBlock)
    def text(self, item):
        self.part = TextToolOutputPart.from_text(item.text, self.read_path)

    @handles(schema.EmbeddedResourceContentBlock)
    def resource(self, item):
        self.dispatch_sync(item.resource)

    @handles(schema.TextResourceContents)
    def text_resource(self, item):
        from agent_comms.tool_results import SENT_MESSAGE_MIME

        if item.mime_type == SENT_MESSAGE_MIME:
            import json
            from agent_comms.field_codec import FieldCodec
            from agent_comms.transcript_events import SentTranscript

            self.part = SentMessageToolOutputPart(FieldCodec.decode(SentTranscript, json.loads(item.text)))
        else:
            self.part = PatchToolOutputPart(item.text) if item.mime_type == 'text/x-diff' else UnrenderedToolOutputPart(item)

    @handles(schema.FileEditToolCallContent)
    def diff(self, item):
        self.part = FileDiffToolOutputPart(item.path, item.old_text, item.new_text)

    @handles(schema.TerminalToolCallContent)
    def terminal(self, item):
        self.part = TerminalToolOutputPart(item.terminal_id)


def decode_content(item: object, read_path: str | None = None) -> ToolOutputPart:
    decoder = ToolContentDecoder(read_path)
    decoder.dispatch_sync(item)
    return decoder.part or UnrenderedToolOutputPart(item)


class ToolOutput:
    """Decoded parts shared by the live and saved line-block renderers."""

    def __init__(self, view: ToolCall) -> None:
        self._view = ref(view)
        self.parts: tuple[ToolOutputPart, ...] = ()
        self.suppress_auto_expansion = False

    @property
    def view(self) -> ToolCall:
        view = self._view()
        assert view is not None
        return view

    @staticmethod
    def capture_parts(tool_call: schema.ToolCall) -> tuple[ToolOutputPart, ...]:
        """Pure ACP interpretation, shared by live ingress and saved workers."""
        raw_input = tool_call.raw_input or {}
        path = (
            raw_input.get("path") or raw_input.get("file_path") or raw_input.get("filePath")
            if isinstance(raw_input, dict) else None
        )
        read_path = path if tool_call.kind == "read" and isinstance(path, str) else None
        return tuple(decode_content(item, read_path) for item in tool_call.content or ())

    def replace(
        self, tool_call: schema.ToolCall, *, parts: tuple[ToolOutputPart, ...] | None = None,
    ) -> None:
        self.suppress_auto_expansion = tool_call.kind == "read"
        self.parts = self.capture_parts(tool_call) if parts is None else parts

    @property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return tuple(block for part in self.parts for block in part.line_blocks())

    @property
    def has_content(self) -> bool:
        return bool(self.line_blocks)

    def preview_fits(self) -> bool:
        dimensions = [
            size for part in self.parts if (size := part.preview_dimensions) is not None
        ]
        return (
            bool(dimensions)
            and sum(size[0] for size in dimensions) <= 16000
            and sum(size[1] for size in dimensions) <= 200
        )

    def sync(self) -> AwaitComplete:
        from toad.widgets.tool_call import ToolContent

        body = self.view.query_one_optional("#tool-content", ToolContent)
        if body is None:
            return AwaitComplete()
        body.update(self.line_blocks if self.view.expanded else ())
        return AwaitComplete()
