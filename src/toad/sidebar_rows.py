"""What a channel's line and a thread's line show in a sidebar list, for every frontend.

The sidebar model's rows (`ChannelRowModel`, `ThreadRowModel`) carry the facts; these faces
decide the text a line draws from them — the unread badge, the pin mark, the name, the line
under it and the hover text — so Textual's rows and Qt's tree lines read the same. Each
frontend's line only paints the text it is handed.

Plain mixins: Textual's widget metaclass refuses an `ABC` base and Qt's shiboken metaclass
clashes with one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.ui_model.sidebar import ChannelRowModel, ThreadRowModel
from ui_theme.scheme import AlternateRowToneColour, SidebarToneColour, ThemeColour

from toad.client.sidebar_lines import DetailedLine
from toad.client.theme_tones import ChannelRowTone
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


class ThreadActionStatus(ABC):
    """Optional in-flight action status text on a sidebar thread row."""

    @abstractmethod
    def thread_busy(self, row: ThreadRowModel) -> bool:
        ...

    @classmethod
    def from_optional(cls, value: str | None) -> ThreadActionStatus:
        return AbsentThreadActionStatus() if value is None else HeldThreadActionStatus(value)


@dataclass(frozen=True)
class AbsentThreadActionStatus(ThreadActionStatus):
    """Absent `ThreadActionStatus` carrying no value."""

    def thread_busy(self, row: ThreadRowModel) -> bool:
        return row.status.is_working()


@dataclass(frozen=True)
class HeldThreadActionStatus(ThreadActionStatus):
    """Held `ThreadActionStatus` carrying its present value."""

    value: str

    def thread_busy(self, row: ThreadRowModel) -> bool:
        return True


class ThreadRowFace:
    """A thread's line in a sidebar list."""

    row_tones: ClassVar[tuple[type[ThemeColour], type[ThemeColour]]] = (
        SidebarToneColour,
        AlternateRowToneColour,
    )

    @staticmethod
    def thread_busy(row: ThreadRowModel, action_status: ThreadActionStatus) -> bool:
        """Whether the line waves (`NameWave`): its thread works, or an action on it runs."""
        return action_status.thread_busy(row)

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

    row_tones: ClassVar[tuple[type[ThemeColour], ...]] = tuple(ChannelRowTone.__subclasses__())

    def present_channel(self, channel: ChannelRowModel, *, counts: type[UnreadCount]) -> None:
        """`counts` is the reader's unread-count setting, which says how the badge reads."""
        self.show_channel_text(ChannelLineText(counts.badge(channel.unread), channel.label(), channel.summary(),
                                               channel.tooltip()))

    @abstractmethod
    def show_channel_text(self, text: ChannelLineText) -> None:
        """Paint the line's text."""
