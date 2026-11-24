"""Structured context, thinking, epistemic claims, and tool calls at the shared UI layer.

Parses compact structured model output (`<think>`, `<ctx>`, `<tool_call>`, `Certainty:`
deduced/assumed claims, `Confidence:`, `[[CTX_TURN ...]]`, `=== SECTION ===`, and
`.live_ctx` budget/knob lines) into a nominal `StructuredPart` hierarchy.

Every frontend (Textual, Qt desktop, Android APK, and Web) inherits the same
`LineBlock` presentation (in chat and transcripts) and collapsible `ContextNode`
tree structure (in Context Explorer) from this one module with zero toolkit imports.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily

from toad.client.line_blocks import (
    Body,
    LineBlock,
    MarkdownMessageBody,
    MutedRole,
    Span,
    Summary,
    ThinkingRole,
    ToolArgumentRole,
    ToolOutputRole,
    ToolVerbRole,
)

_TURN_HEADER = re.compile(r"^\[\[CTX_TURN\s+(\d+)\s+role=([A-Za-z0-9_-]+)\]\]\s*$", re.MULTILINE)
_BANNER_HEADER = re.compile(r"^===\s+([A-Z0-9][A-Z0-9 _./-]{1,60}?)\s+===\s*$", re.MULTILINE)
_BUDGET_LINE = re.compile(r"\[context:\s*([^\]]+)\]")
_CONFIDENCE_LINE = re.compile(r"^\s*Confidence\s*:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_CERTAINTY_ITEM = re.compile(
    r"^\s*[-*]\s*(DEDUCED|ASSUMED|UNKNOWN|REFUTED|OBSERVED)\s*:\s*(.+?)\s*$",
    re.MULTILINE,
)
_FUNCTION_TAG = re.compile(r"<function=([^>]+)>(.*?)</function>", re.DOTALL)
_PARAM_TAG = re.compile(r"<parameter=([^>]+)>(.*?)</parameter>", re.DOTALL)


def compact_preview(text: str, limit: int = 64) -> str:
    """Single-line trimmed preview that stays legible on a 50-column phone screen."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(1, limit - 1)].rstrip() + "…"


class StructuredPart(ABC):
    """One semantic part of a model message or context segment."""

    kind_title: ClassVar[str] = "Section"
    badge_titles: ClassVar[tuple[str, ...]] = ()
    expands_in_tree: ClassVar[bool] = True

    @property
    @abstractmethod
    def text(self) -> str:
        """Plain searchable text carried by this part."""

    @property
    @abstractmethod
    def label(self) -> str:
        """Compact one-line label for tree views and collapsed headers."""

    @property
    def children(self) -> tuple[StructuredPart, ...]:
        return ()

    def detail(self) -> str:
        return self.text

    @abstractmethod
    def line_blocks(self) -> tuple[LineBlock, ...]:
        """Toolkit-neutral line blocks drawn in transcripts and live chat."""

    def wire_blocks(self, row, body_type) -> tuple[LineBlock, ...]:
        """Toolkit-neutral line blocks drawn inside a bus message."""
        return self.line_blocks()


@dataclass(frozen=True)
class CertaintyClaim(StructuredPart):
    """One grounded or assumed epistemic claim from a `Certainty:` audit block."""

    kind_title = "Claim"
    badge_titles = ("Claim",)

    status: str
    statement: str
    basis: str = ""

    @property
    def text(self) -> str:
        return self.formatted()

    @property
    def label(self) -> str:
        return f"{self.status} · {compact_preview(self.statement, 56)}"

    def formatted(self) -> str:
        if self.basis:
            return f"- **{self.status}**: {self.statement}\n  _Basis_: {self.basis}"
        return f"- **{self.status}**: {self.statement}"

    def detail(self) -> str:
        if self.basis:
            return f"{self.status}\n\n{self.statement}\n\nBasis: {self.basis}"
        return f"{self.status}\n\n{self.statement}"

    def line_blocks(self) -> tuple[LineBlock, ...]:
        return (Summary((Span(f"· {self.status}: {self.statement}", ThinkingRole),)),)


@dataclass(frozen=True)
class ThinkingPart(StructuredPart):
    """Visible reasoning (`<think>` or Pi `ThinkingContent`), with parsed Certainty/Confidence."""

    kind_title = "Thinking"
    badge_titles = ("Thinking",)

    raw_text: str
    claims: tuple[CertaintyClaim, ...] = ()
    confidence: str = ""
    streaming: bool = False

    @property
    def text(self) -> str:
        return self.raw_text

    @classmethod
    def from_text(cls, text: str, *, streaming: bool = False) -> ThinkingPart:
        cleaned = text.strip()
        claims: list[CertaintyClaim] = []
        for match in _CERTAINTY_ITEM.finditer(cleaned):
            status = match.group(1).upper()
            body = match.group(2).strip()
            statement, sep, basis = body.partition(" Basis:")
            if not sep:
                statement, sep, basis = body.partition(" basis:")
            claims.append(CertaintyClaim(status, statement.strip(), basis.strip()))
        conf_match = _CONFIDENCE_LINE.search(cleaned)
        confidence = conf_match.group(1).strip() if conf_match else ""
        return cls(
            raw_text=cleaned,
            claims=tuple(claims),
            confidence=confidence,
            streaming=streaming,
        )

    @property
    def summary_title(self) -> str:
        prefix = "Thinking…" if self.streaming else "Thinking"
        pieces: list[str] = [prefix]
        if self.claims:
            counts: dict[str, int] = {}
            for claim in self.claims:
                key = claim.status.lower()
                counts[key] = counts.get(key, 0) + 1
            pieces.append(", ".join(f"{count} {name}" for name, count in counts.items()))
        if self.confidence:
            pieces.append(f"Confidence: {self.confidence}")
        return " · ".join(pieces)

    @property
    def label(self) -> str:
        if self.claims or self.confidence:
            return self.summary_title
        preview = compact_preview(self.raw_text, 56)
        return f"{self.summary_title} · {preview}" if preview else self.summary_title

    @property
    def children(self) -> tuple[StructuredPart, ...]:
        return self.claims

    def detail(self) -> str:
        lines = [self.summary_title]
        if self.claims:
            lines.append("")
            lines.append("Certainty:")
            for claim in self.claims:
                lines.append(claim.formatted())
        if self.raw_text:
            lines.append("")
            lines.append(self.raw_text)
        return "\n".join(lines)

    def line_blocks(self) -> tuple[LineBlock, ...]:
        if not self.raw_text:
            return ()
        header = Summary((Span(f"· {self.summary_title}", ThinkingRole),))
        body = MarkdownMessageBody(self.raw_text, role=ThinkingRole, bar=ThinkingRole).presentation()
        return (header, *body)


@dataclass(frozen=True)
class ContextSectionPart(StructuredPart):
    """One named section inside a compact `<ctx>` / `.live_ctx` document."""

    kind_title = "Section"
    badge_titles = ("Section",)

    heading: str
    body_text: str

    @property
    def text(self) -> str:
        return self.body_text

    @property
    def label(self) -> str:
        preview = compact_preview(self.body_text, 48)
        return f"{self.heading} · {preview}" if preview else self.heading

    def detail(self) -> str:
        return f"{self.heading}\n\n{self.body_text}" if self.body_text else self.heading

    def line_blocks(self) -> tuple[LineBlock, ...]:
        header = Summary((Span(f"· {self.heading}", MutedRole),))
        if not self.body_text.strip():
            return (header,)
        return (header, Body(self.body_text.strip(), role=MutedRole, bar=MutedRole))


@dataclass(frozen=True)
class LiveContextPart(StructuredPart):
    """A compact structured `<ctx>` or `.live_ctx` context block decomposed into sections."""

    kind_title = "Context"
    badge_titles = ("Context",)

    raw_text: str
    title: str = "Context"
    budget: str = ""
    sections: tuple[ContextSectionPart, ...] = ()
    streaming: bool = False

    @property
    def text(self) -> str:
        return self.raw_text

    @classmethod
    def from_text(cls, text: str, *, title: str = "Context", streaming: bool = False) -> LiveContextPart:
        cleaned = text.strip()
        budget_match = _BUDGET_LINE.search(cleaned)
        budget = budget_match.group(1).strip() if budget_match else ""
        sections = _split_context_sections(cleaned)
        return cls(
            raw_text=cleaned,
            title=title,
            budget=budget,
            sections=sections,
            streaming=streaming,
        )

    @property
    def label(self) -> str:
        head = f"{self.title}…" if self.streaming else self.title
        pieces = [head]
        if self.sections:
            count = len(self.sections)
            pieces.append(f"{count} section" if count == 1 else f"{count} sections")
        if self.budget:
            pieces.append(self.budget)
        if len(pieces) == 1:
            preview = compact_preview(self.raw_text, 52)
            if preview:
                pieces.append(preview)
        return " · ".join(pieces)

    @property
    def children(self) -> tuple[StructuredPart, ...]:
        return self.sections

    def detail(self) -> str:
        header = self.label
        if not self.sections:
            return f"{header}\n\n{self.raw_text}" if self.raw_text else header
        rendered = [header]
        for section in self.sections:
            rendered.append(f"\n── {section.heading} ──\n{section.body_text}")
        return "\n".join(rendered)

    def line_blocks(self) -> tuple[LineBlock, ...]:
        header = Summary((Span(f"· {self.label}", MutedRole),))
        if not self.raw_text:
            return (header,)
        return (header, Body(self.raw_text, role=MutedRole, bar=MutedRole))


@dataclass(frozen=True)
class ToolCallPart(StructuredPart):
    """A tool call parsed from `<tool_call>` XML/JSON or a Pi `ToolCallContent`."""

    kind_title = "Tool call"
    badge_titles = ("Tool call",)

    name: str
    arguments_text: str
    raw_text: str = ""

    @property
    def text(self) -> str:
        return self.raw_text or f"{self.name}({self.arguments_text})"

    @classmethod
    def from_call(cls, name: str, arguments: object) -> ToolCallPart:
        args_text = _format_arguments(arguments)
        raw = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False, indent=2)
        return cls(name=name, arguments_text=args_text, raw_text=raw)

    @classmethod
    def from_tag(cls, body: str) -> ToolCallPart:
        cleaned = body.strip()
        fn_match = _FUNCTION_TAG.search(cleaned)
        if fn_match:
            name = fn_match.group(1).strip()
            params = {
                m.group(1).strip(): m.group(2).strip()
                for m in _PARAM_TAG.finditer(fn_match.group(2))
            }
            return cls(name=name, arguments_text=_format_arguments(params), raw_text=cleaned)
        try:
            decoded = json.loads(cleaned)
        except ValueError:
            decoded = None
        if isinstance(decoded, dict) and isinstance(decoded.get("name"), str):
            return cls(
                name=decoded["name"],
                arguments_text=_format_arguments(decoded.get("arguments", {})),
                raw_text=cleaned,
            )
        return cls(name="tool_call", arguments_text=compact_preview(cleaned, 64), raw_text=cleaned)

    @property
    def label(self) -> str:
        preview = compact_preview(self.arguments_text, 48)
        return f"Tool · {self.name}({preview})" if preview else f"Tool · {self.name}"

    def detail(self) -> str:
        lines = [f"Tool call · {self.name}"]
        if self.arguments_text:
            lines.append("")
            lines.append(self.arguments_text)
        return "\n".join(lines)

    def line_blocks(self) -> tuple[LineBlock, ...]:
        preview = compact_preview(self.arguments_text, 72)
        spans = (
            Span("· Tool ", ToolVerbRole),
            Span(self.name, ToolVerbRole),
            *(
                (Span(f"  {preview}", ToolArgumentRole),)
                if preview
                else ()
            ),
        )
        if "\n" not in self.arguments_text and len(self.arguments_text) <= 72:
            return (Summary(spans),)
        return (Summary(spans), Body(self.arguments_text, role=ToolOutputRole, bar=ToolOutputRole))


@dataclass(frozen=True)
class AnswerPart(StructuredPart):
    """Plain assistant answer text outside `<think>`, `<ctx>`, and `<tool_call>` blocks."""

    kind_title = "Answer"
    expands_in_tree = False

    body_text: str

    @property
    def text(self) -> str:
        return self.body_text

    @property
    def label(self) -> str:
        preview = compact_preview(self.body_text, 56)
        return f"Answer · {preview}" if preview else "Answer"

    def line_blocks(self) -> tuple[LineBlock, ...]:
        if not self.body_text.strip():
            return ()
        return MarkdownMessageBody(self.body_text).presentation()

    def wire_blocks(self, row, body_type) -> tuple[LineBlock, ...]:
        if not self.body_text.strip():
            return ()
        return (body_type(row, self.body_text),)


def _format_arguments(arguments: object) -> str:
    if isinstance(arguments, dict):
        if len(arguments) == 1:
            only_value = next(iter(arguments.values()))
            if isinstance(only_value, str):
                return only_value
        return "\n".join(
            f"{key}: {value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}"
            for key, value in arguments.items()
        )
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False, indent=2)


def _split_context_sections(text: str) -> tuple[ContextSectionPart, ...]:
    """Split `.live_ctx` / `[[CTX_TURN ...]]` / `=== SECTION ===` blocks into child sections."""
    turn_matches = list(_TURN_HEADER.finditer(text))
    if turn_matches:
        sections: list[ContextSectionPart] = []
        preamble = text[: turn_matches[0].start()].strip()
        if preamble:
            sections.append(ContextSectionPart("Header", preamble))
        for index, match in enumerate(turn_matches):
            end = turn_matches[index + 1].start() if index + 1 < len(turn_matches) else len(text)
            body = text[match.end() : end].strip()
            sections.append(ContextSectionPart(f"Turn {match.group(1)} · {match.group(2)}", body))
        return tuple(sections)

    banner_matches = list(_BANNER_HEADER.finditer(text))
    if banner_matches:
        sections = []
        preamble = text[: banner_matches[0].start()].strip()
        if preamble:
            sections.append(ContextSectionPart("Header", preamble))
        for index, match in enumerate(banner_matches):
            heading = match.group(1).strip()
            if heading.upper().startswith("END "):
                continue
            end = banner_matches[index + 1].start() if index + 1 < len(banner_matches) else len(text)
            body = text[match.end() : end].strip()
            if body:
                sections.append(ContextSectionPart(heading.title(), body))
        return tuple(sections)

    return ()


class StructuredTag(DeclaredFamily, affix="Tag"):
    """Inline XML-style tag emitted by reasoning/context models; decoded once at the tag boundary."""

    @classmethod
    @abstractmethod
    def decode_block(cls, inner: str, *, streaming: bool) -> tuple[StructuredPart, ...]: ...


class ThinkTag(StructuredTag):
    @classmethod
    def decode_block(cls, inner: str, *, streaming: bool) -> tuple[StructuredPart, ...]:
        if not inner.strip() and not streaming:
            return ()
        return (ThinkingPart.from_text(inner, streaming=streaming),)


class CtxTag(StructuredTag):
    @classmethod
    def decode_block(cls, inner: str, *, streaming: bool) -> tuple[StructuredPart, ...]:
        if not inner.strip() and not streaming:
            return ()
        return (LiveContextPart.from_text(inner, title="Context (<ctx>)", streaming=streaming),)


class ToolCallTag(StructuredTag):
    @classmethod
    def decode_block(cls, inner: str, *, streaming: bool) -> tuple[StructuredPart, ...]:
        if not inner.strip():
            return ()
        return (ToolCallPart.from_tag(inner),)


_TAG_OPEN = re.compile(
    "<(" + "|".join(re.escape(name) for name in StructuredTag.names()) + ")>",
    re.IGNORECASE,
)


def has_structured_tags(text: str) -> bool:
    """Fast O(n) check before splitting message or transcript text."""
    return "<" in text and _TAG_OPEN.search(text) is not None


def parse_structured_text(text: str) -> tuple[StructuredPart, ...]:
    """Split text containing declared structured tags (`<think>`, `<ctx>`, `<tool_call>`) into parts.

    Handles both closed tags and streaming unclosed tags at end-of-text so live replies
    never flash raw XML tags. Plain text without structured tags returns `(AnswerPart(text),)`.
    """
    if not has_structured_tags(text):
        return (AnswerPart(text),)

    parts: list[StructuredPart] = []
    cursor = 0
    length = len(text)
    lower = text.lower()
    while cursor < length:
        match = _TAG_OPEN.search(text, cursor)
        if match is None:
            tail = text[cursor:].strip()
            if tail:
                parts.append(AnswerPart(tail))
            break
        before = text[cursor : match.start()].strip()
        if before:
            parts.append(AnswerPart(before))
        tag_name = match.group(1).lower()
        tag_member = StructuredTag.member_named(tag_name)
        close_token = f"</{tag_name}>"
        close_index = lower.find(close_token, match.end())
        if close_index < 0:
            inner = text[match.end() :]
            streaming = True
            cursor = length
        else:
            inner = text[match.end() : close_index]
            streaming = False
            cursor = close_index + len(close_token)
        parts.extend(tag_member.decode_block(inner, streaming=streaming))
    return tuple(parts)


def format_structured_detail(text: str) -> str:
    """Render structured sections cleanly for Context Explorer detail panes; plain text passes through."""
    sections = parse_context_sections(text)
    if not sections:
        return text
    return "\n\n".join(section.detail() for section in sections)


def parse_context_sections(text: str) -> tuple[StructuredPart, ...]:
    """Decompose a Context Explorer segment into collapsible structured child parts.

    Returns an empty tuple for ordinary unstructured text so simple segments stay flat.
    """
    cleaned = text.strip()
    if not cleaned:
        return ()
    if has_structured_tags(cleaned):
        return parse_structured_text(cleaned)
    sections = _split_context_sections(cleaned)
    if sections:
        return sections
    if _CERTAINTY_ITEM.search(cleaned):
        return (ThinkingPart.from_text(cleaned),)
    return ()
