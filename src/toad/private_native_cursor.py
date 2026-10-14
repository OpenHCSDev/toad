"""Bounded, read-only native-history provenance. Never input disposition.

Only validated scope/status/revision and a payload digest survive parsing; raw
proof identifiers/content are not passed to the presentation layer.
"""

from __future__ import annotations

from typing import ClassVar

from agent_comms.declared_family import DeclaredFamily


class CursorStatus(DeclaredFamily, affix="CursorStatus"):
    """One decoded cursor state owns its full UI presentation."""

    label: ClassVar[str]
    summary: ClassVar[str] = ""
    attention: ClassVar[bool] = False

    @classmethod
    def external(cls, value: str | None) -> type[CursorStatus] | None:
        if value is None:
            return None
        return cls.decode(value)


class PendingCursorStatus(CursorStatus):
    label = "Checking bus input verification…"
    summary = "Bus input verification pending"


class ProvenCursorStatus(CursorStatus):
    label = "Bus history: prior messages included in model input"


class CoverageOnlyCursorStatus(CursorStatus):
    label = "Bus history: checked; no model input yet"


class NoneCursorStatus(CursorStatus):
    label = "Bus history: no verified input for this session yet"


class UnavailableCursorStatus(CursorStatus):
    label = "Bus input verification unavailable — check the ACP log; saved history is separate"
    summary = "Bus input verification unavailable"
    attention = True


TOOLTIP = (
    "Current bus-history verification for this agent session. Pending means the "
    "attachment is still waiting for its original observation; it is not a failure. "
    "A verified input can be a short relevance check, not a full reply. This does "
    "not confirm receipt or completion of your latest message. Saved transcript "
    "availability is reported separately. If verification is unavailable, check "
    "the ACP log; do not resend input solely because proof is missing."
)
