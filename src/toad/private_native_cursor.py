"""Size-limited, read-only native-history source. Never decides what happens to input.

Only validated scope/status/revision and a payload digest survive parsing; raw
proof identifiers/content are not passed to the presentation layer.
"""

from __future__ import annotations

from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.registry.thread_presentation import ThreadPresentationStatus


class CursorStatus(DeclaredFamily, affix="CursorStatus"):
    """One decoded cursor state owns its full UI presentation."""

    label: ClassVar[str]
    summary: ClassVar[str] = ""
    visible: ClassVar[bool] = True

    @classmethod
    def external(cls, value: str | None) -> type[CursorStatus]:
        if value is None:
            return HiddenCursorStatus
        return cls.member_named(value)

    @classmethod
    def present_status(cls, status: ThreadPresentationStatus) -> ThreadPresentationStatus:
        return status


class HiddenCursorStatus(CursorStatus):
    """This session does not expose native cursor verification."""

    label = ""
    visible = False


class PendingCursorStatus(CursorStatus):
    label = "Checking whether the agent has the earlier messages…"
    summary = "Checking earlier messages"


class ProvenCursorStatus(CursorStatus):
    label = "The agent has the earlier messages"


class CoverageOnlyCursorStatus(CursorStatus):
    label = "Earlier messages are here; the agent has not been given them yet"


class NoneCursorStatus(CursorStatus):
    label = "No earlier messages have reached the agent yet"


class UnavailableCursorStatus(CursorStatus):
    label = "Cannot tell whether the agent has the earlier messages — the ACP log says why"
    summary = "Cannot tell about earlier messages"

    @classmethod
    def present_status(cls, status: ThreadPresentationStatus) -> ThreadPresentationStatus:
        return status.with_attention(cls.summary)


TOOLTIP = (
    "Whether this agent has actually been given the earlier messages from the bus.\n\n"
    "Checking is not a failure: the answer has not come back yet. The agent having "
    "them does not mean it has answered your latest message. The saved transcript is "
    "a separate thing, reported on its own line.\n\n"
    "If this cannot tell, the ACP log says why. Do not resend a message just because "
    "this line has nothing to say."
)
"""What the history line means, in the words a person would use.

It read: "Current bus-history verification for this agent session. Pending means the
attachment is still waiting for its original observation; it is not a failure." Every
noun there is this code's own bookkeeping - verification, attachment, observation,
coverage - and the reader has to translate all four before learning the one fact they
wanted, which is whether the agent has their earlier messages (rules/talk.md; Tristan,
2026-11-08, on the queue tooltip he screenshotted: none of this in the UI, and change
it wherever it is found)."""
