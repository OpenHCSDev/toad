"""Saved native session journals in the format Pi writes.

Pi owns the format; Core only reads it. A line a test writes by hand drifts
(an assistant message's content is always an array of blocks, for one), so
every line written here is read back through Core and must decode as the
message it was meant to be.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent_comms.field_codec import RecordedTimestamp
from agent_comms.native_entries import MessageEntry, NativeEntry, RootEntry, SessionEntry
from agent_comms.pi_payloads import (
    AssistantMessage, PiMessage, PiOmitted, ReportedText, TextContent, UnknownMessage, UserMessage,
)


def message_entry(message: PiMessage, *, id: str, parent: str | None = None) -> dict:
    """One journal message, encoded by its declared Core record."""
    return MessageEntry(
        id=id, parent_id=RootEntry.from_input(parent),
        timestamp=RecordedTimestamp.written(datetime(2026, 10, 18, tzinfo=UTC)),
        message=message,
    ).to_wire()


def assistant_entry(text: str, *, id: str, parent: str | None = None) -> dict:
    return message_entry(AssistantMessage(content=(TextContent(text),)), id=id, parent=parent)


def user_entry(text: str, *, id: str, parent: str | None = None, input_id: str | None = None) -> dict:
    """A user line; `input_id` is the identity Core gave the input when it sent it to the agent."""
    return message_entry(UserMessage(
        content=(TextContent(text),),
        input_id=PiOmitted() if input_id is None else ReportedText(input_id),
    ), id=id, parent=parent)


def write_journal(path: Path, *entries: dict) -> Path:
    """Write `entries` as the lines of a session journal and return its path."""
    for entry in entries:
        decoded = NativeEntry.read(json.dumps(entry).encode())
        if isinstance(decoded, MessageEntry) and isinstance(decoded.message, UnknownMessage):
            raise ValueError(f"Core does not read this journal line as a known message: {entry}")
    header = SessionEntry(id=uuid4().hex, version=3, cwd=str(path.parent),
                          timestamp=RecordedTimestamp.written(datetime.now(UTC)))
    path.write_text(json.dumps(header.to_wire()) + "\n"
                    + "".join(json.dumps(entry) + "\n" for entry in entries))
    return path
