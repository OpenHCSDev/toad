"""Decoded tool output owns its presentation and preparation lifetime.

ACP dictionaries end at ``decode_content``. Presentation cases and the mounted
output owner operate on captured values, including when an adapter mutates an
earlier dictionary or changes Read's filename without changing its text.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from difflib import unified_diff
from functools import cached_property, partial
from pathlib import PurePath
import re
from weakref import ref

from agent_comms.declared_family import DeclaredFamily
from agent_comms.transcript_events import SentTranscript, ToolEndTranscript
from agent_comms.tool_results import ToolDiff, ToolText
from agent_comms.tool_declaration import PathTool
from agent_comms.sent_message import PublishedSentMessage
from agent_comms.transcript_receipts import AssignedTranscriptSource
from textual.await_complete import AwaitComplete
from rich.text import Text

from acp import schema
from agent_comms.mro_dispatch import MroDispatch, handles
from toad.line_blocks import Body, LineBlock, MutedRole, ToolOutputRole
from toad.patch import parse_patch, parse_numbered_patch
from toad.message_rows import MessageRow
from toad.rich_preparation import RichTextBody


class ToolDetails(ABC):
    """A tool output part's only rendered details contract."""

    @property
    @abstractmethod
    def line_blocks(self) -> tuple[LineBlock, ...]: ...


class ToolOutputPart(ToolDetails, DeclaredFamily, affix="ToolOutputPart"):
    """A captured output value; each case owns its semantic detail blocks."""

    @property
    def has_details(self) -> bool:
        return True

    def permission_preview(self) -> ToolOutputPart | None:
        """Permission previews admit only text and file diffs."""
        return None

    @property
    def sent_reports(self) -> tuple[SentTranscript, ...]:
        return ()

    @property
    def standalone_messages(self) -> tuple[PublishedSentMessage, ...]:
        return ()

    def project_messages(self, resolved) -> ToolOutputPart:
        return self

    def for_body_sources(self, supplied) -> ToolOutputPart:
        return self

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


class PlainTextToolOutputPart(LiteralTextToolOutputPart):
    @classmethod
    def accepts(cls, text: str, read_path: str | None) -> bool:
        return read_path is None

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return (Body(self.text, role=ToolOutputRole, bar=MutedRole, markdown=False),)


class AnsiTextToolOutputPart(SpecificTextToolOutputPart):
    @classmethod
    def accepts(cls, text: str, read_path: str | None) -> bool:
        return read_path is None and "\x1b" in text

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return (RichTextBody(Text.from_ansi(self.text)),)


class MarkdownToolOutputPart(SpecificTextToolOutputPart):
    @classmethod
    def accepts(cls, text: str, read_path: str | None) -> bool:
        return read_path is None and "\x1b" not in text and (
            "```" in text or re.search(r"^#{1,6}\s.*$", text, re.MULTILINE) is not None
        )

    @cached_property
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

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return (Body.code(self.text, PurePath(self.path).suffix.removeprefix("."), bar=MutedRole),)


@dataclass(frozen=True)
class PatchToolOutputPart(ToolOutputPart):
    source: str

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return (parse_patch(self.source),)

    @property
    def preview_dimensions(self) -> tuple[int, int]:
        return len(self.source), self.source.count("\n")


@dataclass(frozen=True)
class NumberedPatchToolOutputPart(ToolOutputPart):
    """Pi's retained numbered edits already contain their reported line numbers."""

    source: str

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return (parse_numbered_patch(self.source),)


@dataclass(frozen=True)
class SentMessageToolOutputPart(ToolOutputPart):
    """A report without source proof retains its full, non-interactive evidence."""

    message: SentTranscript
    literal: str

    @classmethod
    def capture(cls, message, literal=None):
        if literal is None:
            import json
            from agent_comms.field_codec import FieldCodec

            literal = json.dumps(FieldCodec.encode(message))
        return cls(message, literal)

    @property
    def sent_reports(self):
        return (self.message,)

    def project_messages(self, resolved):
        decoder = ToolContentDecoder(report=self)
        decoder.dispatch_sync(resolved[id(self.message)])
        return decoder.part

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return PlainTextToolOutputPart(self.literal).line_blocks


@dataclass(frozen=True)
class PublishedSentMessageToolOutputPart(ToolOutputPart):
    """A proved publication retains its source even without a separate body."""

    message: PublishedSentMessage
    literal: str

    def for_body_sources(self, supplied):
        return (self.with_body() if self.message.reference in supplied
                else self.without_body())

    def with_body(self):
        return SuppliedSentMessageToolOutputPart(self.message, self.literal)

    def without_body(self):
        return self

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return PlainTextToolOutputPart(self.literal).line_blocks


class SuppliedSentMessageToolOutputPart(PublishedSentMessageToolOutputPart):
    """Only a supplied normal body permits compact tool details."""

    @property
    def standalone_messages(self):
        return (self.message,)

    def with_body(self):
        return self

    def without_body(self):
        return PublishedSentMessageToolOutputPart(self.message, self.literal)

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return (MessageRow.sent(self.message.message).header,)


@dataclass(frozen=True)
class FileDiffToolOutputPart(ToolOutputPart):
    path: str
    old_text: str | None
    new_text: str

    def permission_preview(self) -> ToolOutputPart:
        return self

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        lines = unified_diff((self.old_text or "").splitlines(), self.new_text.splitlines(),
                             self.path, self.path, lineterm="")
        source = "\n".join(lines)
        return (parse_patch(source),) if source else ()


class OmittedToolOutputPart(ToolOutputPart):
    """Content with no details in this view, including externally owned terminals."""

    @property
    def has_details(self) -> bool:
        return False

    @cached_property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return ()


@dataclass(frozen=True)
class UnrenderedToolOutputPart(OmittedToolOutputPart):
    """ACP media without a text projection has no rendered details."""

    source: object


@dataclass(frozen=True)
class TerminalToolOutputPart(OmittedToolOutputPart):
    """ACP terminal output is projected by its existing terminal owner."""

    terminal_id: str

class ToolContentDecoder(MroDispatch):
    def __init__(self, read_path=None, *, report=None):
        self.read_path = read_path
        self.report = report
        self.part = None

    @handles(schema.ContentToolCallContent)
    def content(self, item):
        self.dispatch_sync(item.content)

    @handles(schema.TextContentBlock, ToolText)
    def text(self, item):
        self.part = TextToolOutputPart.from_text(item.text, self.read_path)

    @handles(schema.EmbeddedResourceContentBlock)
    def resource(self, item):
        self.dispatch_sync(item.resource)

    @handles(schema.TextResourceContents, ToolDiff)
    def text_resource(self, item):
        from agent_comms.tool_results import SENT_MESSAGE_MIME

        if item.mime_type == SENT_MESSAGE_MIME:
            import json
            from agent_comms.field_codec import FieldCodec
            try:
                message = FieldCodec.decode(SentTranscript, json.loads(item.text))
            except (TypeError, ValueError):
                # Unsupported or malformed external evidence stays complete.
                self.part = PlainTextToolOutputPart(item.text)
            else:
                self.part = SentMessageToolOutputPart.capture(message, item.text)
        elif item.mime_type == 'application/vnd.agent-comms.numbered-diff':
            self.part = NumberedPatchToolOutputPart(item.text)
        else:
            self.part = PatchToolOutputPart(item.text) if item.mime_type == 'text/x-diff' else UnrenderedToolOutputPart(item)

    @handles(SentTranscript)
    def sent_report(self, message):
        self.part = self.report or SentMessageToolOutputPart.capture(message)

    @handles(PublishedSentMessage)
    def published_message(self, message):
        assert self.report is not None
        self.part = SuppliedSentMessageToolOutputPart(message, self.report.literal)

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
    def capture_parts(tool_call: schema.ToolCall, *, content=None) -> tuple[ToolOutputPart, ...]:
        """Pure ACP interpretation, shared by live ingress and saved workers."""
        read_path = (PathTool.recorded_path(tool_call.raw_input) or None) if tool_call.kind == "read" else None
        contents = (tool_call.content or ()) if content is None else content
        return tuple(decode_content(item, read_path) for item in contents)

    @staticmethod
    def project_sent(parts, scope):
        reports = tuple(message for part in parts for message in part.sent_reports)
        if scope is None or not reports:
            return parts
        resolved = dict(zip(map(id, reports), AssignedTranscriptSource.open(scope).resolve_sent(reports)))
        return ToolOutput.apply_sent(parts, resolved)

    @staticmethod
    def apply_sent(parts, resolved):
        return tuple(part.project_messages(resolved) for part in parts)

    @classmethod
    def capture_recorded(cls, status, events):
        end = next((event for event in reversed(events) if isinstance(event, ToolEndTranscript)), None)
        return cls.capture_parts(status.call, content=end.result_parts if end is not None else ())

    @classmethod
    def capture_projection(cls, status, scope):
        return status.project_output(cls.capture_parts(status.call),
                                     partial(cls.project_sent, scope=scope))

    def replace(
        self, tool_call: schema.ToolCall, *, parts: tuple[ToolOutputPart, ...] | None = None,
    ) -> None:
        self.suppress_auto_expansion = tool_call.kind == "read"
        self.parts = self.capture_parts(tool_call) if parts is None else parts

    @property
    def line_blocks(self) -> tuple[LineBlock, ...]:
        return tuple(block for part in self.parts for block in part.line_blocks)

    @property
    def has_content(self) -> bool:
        return any(part.has_details for part in self.parts)

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
        from toad.widgets.tool_content import ToolContent

        body = self.view.query_one_optional("#tool-content", ToolContent)
        if body is None:
            return AwaitComplete()
        body.update(self.line_blocks if self.view.expanded else ())
        return AwaitComplete()
