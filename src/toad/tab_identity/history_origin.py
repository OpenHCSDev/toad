"""Which tab a conversation tab was opened from, as tabs saved by an older Toad record it.

No tab owns a conversation now; these declarations exist only so those saved rows decode
(HistoryTab), and each such tab is then removed on restore.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_comms.nominal.declared_family import DeclaredFamily

from toad.tab_identity import SessionTabIdentity


class HistoryOrigin(DeclaredFamily, affix="HistoryOrigin"):
    """The opener a saved conversation tab recorded."""


@dataclass(frozen=True)
class WelcomeHistoryOrigin(HistoryOrigin):
    """Opened from the welcome view."""


@dataclass(frozen=True)
class SessionHistoryOrigin(HistoryOrigin):
    """Opened from an agent or mailbox tab."""

    identity: SessionTabIdentity
