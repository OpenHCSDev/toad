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


def message_entry(role: str, text: str, *, id: str, parent: str | None = None) -> dict:
    """One ``message`` line: `role` is ``assistant`` or ``user``."""
    return {"type": "message", "id": id, "parentId": parent, "timestamp": "2026-10-18T00:00:00+00:00",
            "message": {"role": role, "content": [{"type": "text", "text": text}]}}


def assistant_entry(text: str, *, id: str, parent: str | None = None) -> dict:
    return message_entry("assistant", text, id=id, parent=parent)


def user_entry(text: str, *, id: str, parent: str | None = None, input_id: str | None = None) -> dict:
    """A user line; `input_id` is the identity Core gave the input when it sent it to the agent."""
    entry = message_entry("user", text, id=id, parent=parent)
    if input_id is not None:
        entry["message"]["inputId"] = input_id
    return entry


def write_journal(path: Path, *entries: dict) -> Path:
    """Write `entries` as the lines of a session journal and return its path."""
    from agent_comms.field_codec import RecordedTimestamp
    from agent_comms.native_entries import MessageEntry, NativeEntry, SessionEntry
    from agent_comms.pi_payloads import UnknownMessage

    for entry in entries:
        decoded = NativeEntry.read(json.dumps(entry).encode())
        if isinstance(decoded, MessageEntry) and isinstance(decoded.message, UnknownMessage):
            raise ValueError(f"Core does not read this journal line as a known message: {entry}")
    header = SessionEntry(id=uuid4().hex, version=3, cwd=str(path.parent),
                          timestamp=RecordedTimestamp.written(datetime.now(UTC)))
    path.write_text(json.dumps(header.to_wire()) + "\n"
                    + "".join(json.dumps(entry) + "\n" for entry in entries))
    return path
