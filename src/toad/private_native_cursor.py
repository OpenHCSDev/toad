"""Bounded, read-only native-history provenance. Never input disposition.

Only validated scope/status/revision and a payload digest survive parsing; raw
proof identifiers/content are not passed to the presentation layer.
"""

from __future__ import annotations

from enum import Enum


class CursorStatus(str, Enum):
    """One decoded cursor state owns its full UI presentation."""

    def __new__(cls, value: str, label: str, summary: str = "", attention: bool = False):
        member = str.__new__(cls, value)
        member._value_ = value
        member.label = label
        member.summary = summary
        member.attention = attention
        return member

    PENDING = "pending", "Checking bus input verification…", "Bus input verification pending"
    PROVEN = "proven", "Bus history: prior messages included in model input"
    COVERAGE_ONLY = "coverage_only", "Bus history: checked; no model input yet"
    NONE = "none", "Bus history: no verified input for this session yet"
    UNAVAILABLE = (
        "unavailable",
        "Bus input verification unavailable — check the ACP log; saved history is separate",
        "Bus input verification unavailable",
        True,
    )

    @classmethod
    def decode(cls, value: str | None) -> "CursorStatus | None":
        if value is None:
            return None
        try:
            return cls(value)
        except ValueError:
            return cls.UNAVAILABLE

TOOLTIP = (
    "Current bus-history verification for this agent session. Pending means the "
    "attachment is still waiting for its original observation; it is not a failure. "
    "A verified input can be a short relevance check, not a full reply. This does "
    "not confirm receipt or completion of your latest message. Saved transcript "
    "availability is reported separately. If verification is unavailable, check "
    "the ACP log; do not resend input solely because proof is missing."
)
