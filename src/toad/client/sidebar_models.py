"""Sidebar model values shared by conversations and native views."""

from __future__ import annotations

from agent_comms.display_order import ThreadSort
from agent_comms.ui_model.sidebar import ChannelRowModel
from agent_comms.ui_model.unread import UnobservedUnread


class UnpaintedChannel(ChannelRowModel):
    """An unobserved channel has no painted fields or known members.

    Its counts are not zero, they are unknown, so it paints nothing rather than
    claiming 0/0 agents on the row's second line.
    """

    def __init__(self, name: str) -> None:
        super().__init__(
            name, False, 0, 0, (), UnobservedUnread(), 0, (), frozenset(), ThreadSort
        )

    def label(self) -> str:
        return ""

    def summary(self) -> str:
        return ""

    def tooltip(self) -> str:
        return ""
