"""What a channel's line and a thread's line show in a sidebar list, for every frontend.

The sidebar model's rows (`ChannelRowModel`, `ThreadRowModel`) carry the facts; these faces
decide the text a line draws from them — the unread badge, the pin mark, the name, the line
under it and the hover text — so Textual's rows and Qt's tree lines read the same. Each
frontend's line only paints the text it is handed.

Plain mixins: Textual's widget metaclass refuses an `ABC` base and Qt's shiboken metaclass
clashes with one.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.ui_model.sidebar import ChannelRowModel, ThreadRowModel
from ui_theme.scheme import AlternateRowToneColour, SidebarToneColour, ThemeColour

from toad.client.sidebar_lines import DetailedLine
from toad.client.theme_tones import ChannelAlternateRowToneColour, ChannelRowToneColour
from toad.setting_choices import UnreadCount


@dataclass(frozen=True)
class ThreadLineText:
    """A thread line's text: the unread badge, the pin mark, the name, the line under it
    (a pending action's own status while one runs, else the thread's summary), the hover."""

    badge: str
    pin: str
    name: str
    detail: str
    tooltip: str

    @property
    def prefix(self) -> str:
        """What precedes the name on the first row: the badge, then the pin mark."""
        return DetailedLine.status_prefix(self.badge) + self.pin


class ThreadRowFace:
    """A thread's line in a sidebar list."""

    row_tones: ClassVar[tuple[type[ThemeColour], type[ThemeColour]]] = (
        SidebarToneColour,
        AlternateRowToneColour,
    )

    @staticmethod
    def thread_busy(row: ThreadRowModel, action_status: str | None) -> bool:
        """Whether the line waves (`NameWave`): its thread works, or an action on it runs."""
        return action_status is not None or row.status.is_working()

    def present_thread(self, row: ThreadRowModel, *, pinned: bool, action_status: str | None,
                       counts: type[UnreadCount]) -> None:
        """`counts` is the reader's unread-count setting, which says how the badge reads."""
        self.show_thread_text(ThreadLineText(
            badge=counts.badge(row.unread),
            pin="* " if pinned else "",
            name=row.label,
            detail=action_status if action_status is not None else row.summary,
            tooltip=row.tooltip(pinned=pinned, pending_detail=action_status),
        ))

    @abstractmethod
    def show_thread_text(self, text: ThreadLineText) -> None:
        """Paint the line's text."""


@dataclass(frozen=True)
class ChannelLineText:
    """A channel line's text: its unread badge, its label, the line under it, the hover."""

    badge: str
    label: str
    summary: str
    tooltip: str


class ChannelRowFace:
    """A channel's line in a sidebar list."""

    row_tones: ClassVar[tuple[type[ThemeColour], type[ThemeColour]]] = (
        ChannelRowToneColour,
        ChannelAlternateRowToneColour,
    )

    def present_channel(self, channel: ChannelRowModel, *, counts: type[UnreadCount]) -> None:
        """`counts` is the reader's unread-count setting, which says how the badge reads."""
        self.show_channel_text(ChannelLineText(counts.badge(channel.unread), channel.label(), channel.summary(),
                                               channel.tooltip()))

    @abstractmethod
    def show_channel_text(self, text: ChannelLineText) -> None:
        """Paint the line's text."""
