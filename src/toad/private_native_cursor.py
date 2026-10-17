"""Size-limited, read-only native-history source. Never decides what happens to input.

Only validated scope/status/revision and a payload digest survive parsing; raw
proof identifiers/content are not passed to the presentation layer.
"""

from __future__ import annotations

from typing import ClassVar

from agent_comms.declared_family import DeclaredFamily
from agent_comms.thread_presentation import ThreadPresentationStatus


class CursorStatus(DeclaredFamily, affix="CursorStatus"):
    """One decoded cursor state owns its full UI presentation."""

    label: ClassVar[str]
    summary: ClassVar[str] = ""
    visible: ClassVar[bool] = True

    @classmethod
    def external(cls, value: str | None) -> type[CursorStatus]:
        if value is None:
            return HiddenCursorStatus
        return cls.decode(value)

    @classmethod
    def present_status(cls, status: ThreadPresentationStatus) -> ThreadPresentationStatus:
        return status


class HiddenCursorStatus(CursorStatus):
    """This session does not expose native cursor verification."""

    label = ""
    visible = False


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

    @classmethod
    def present_status(cls, status: ThreadPresentationStatus) -> ThreadPresentationStatus:
        return status.with_attention(cls.summary)


TOOLTIP = (
    "Current bus-history verification for this agent session. Pending means the "
    "attachment is still waiting for its original observation; it is not a failure. "
    "A verified input can be a short relevance check, not a full reply. This does "
    "not confirm that your latest message was received or completed. Saved transcript "
    "availability is reported separately. If verification is unavailable, check "
    "the ACP log; do not resend input solely because proof is missing."
)
