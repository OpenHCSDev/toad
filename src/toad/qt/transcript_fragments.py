"""Qt's data-only transcript fragment family.

These declarations cross the renderer process boundary.  They deliberately live outside
``toad.qt.history``: constructing transcript data must not import Qt's widget, gesture,
animation and navigation graph into a render worker.  The UI history consumes these same
nominal members; it does not redeclare a renderer-only shadow family.
"""

from dataclasses import dataclass

from agent_comms.messaging.messages import ConversationRole, Membership, NoticeRole

from toad.client.fragments import EvidencedFragment, MembershipText, WireMessage
from toad.client.transcript_fragments import (
    BusMessageFragment,
    ContextTranscriptFragment,
    FragmentClasses,
    SentMessageFragment,
    ToolTranscriptFragment,
    TranscriptFragment,
)


class QtWireFragment(EvidencedFragment, TranscriptFragment):
    """The root of Qt's wire fragments and a shared transcript fragment."""


class QtMembershipFragment(MembershipText, QtWireFragment, shows=(Membership,)):
    """Someone joined or left, drawn by Qt."""


class QtMessageFragment(
    WireMessage,
    BusMessageFragment,
    QtWireFragment,
    shows=(ConversationRole, NoticeRole),
):
    """A bus message, whether decoded from wire history or transcript history."""


class QtToolTranscriptFragment(ToolTranscriptFragment):
    """A tool call whose canonical blocks are painted by Qt's row delegate."""


class QtContextTranscriptFragment(ContextTranscriptFragment):
    """Coordination context drawn by Qt."""


@dataclass(kw_only=True)
class QtSentMessageFragment(SentMessageFragment, EvidencedFragment):
    """A sent bus message carrying the evidence used by Qt's read marker."""

    evidence: object | None = None


QT_FRAGMENT_CLASSES = FragmentClasses(
    transcript=TranscriptFragment,
    context=QtContextTranscriptFragment,
    bus_message=QtMessageFragment,
    sent_message=QtSentMessageFragment,
    tool=QtToolTranscriptFragment,
)
"""The one Qt fragment-family declaration used by both renderer and UI."""
