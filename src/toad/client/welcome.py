"""What Toad's welcome shows, for every frontend: its banner, and which of the sidebar
model's rows each section lists under which title. Each frontend draws them."""

from __future__ import annotations

from typing import ClassVar

from agent_comms.ui_model.sidebar import ChannelRowModel, SidebarModel

from toad.constants import ALL_COMMS_TARGET
from toad.setting_choices import UnreadCount
from toad.sidebar_rows import ChannelLineText


class WelcomeBanner:
    """The app's name, drawn large on the welcome."""

    TEXT = "\n".join(
        (
            " ██████╗ ██████╗ ███╗   ███╗███╗   ███╗███████╗",
            "██╔════╝██╔═══██╗████╗ ████║████╗ ████║██╔════╝",
            "██║     ██║   ██║██╔████╔██║██╔████╔██║███████╗",
            "██║     ██║   ██║██║╚██╔╝██║██║╚██╔╝██║╚════██║",
            "╚██████╗╚██████╔╝██║ ╚═╝ ██║██║ ╚═╝ ██║███████║",
            " ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝     ╚═╝╚══════╝",
        )
    )


class WelcomeListing:
    """Some of the sidebar model's rows, under a title. A plain parent: each frontend's
    section composes it with its own widget base and metaclass."""

    TITLE: ClassVar[str] = ""
    LIMIT: ClassVar[int] = 8

    def keys(self, model: SidebarModel) -> tuple[str, ...]:
        raise NotImplementedError

    def listed(self, model: SidebarModel) -> tuple[str, ...]:
        return self.keys(model)[: self.LIMIT]


class ChannelListing(WelcomeListing):
    """The channels, in the order chosen for the sidebar."""

    TITLE = "Channels"

    def keys(self, model: SidebarModel) -> tuple[str, ...]:
        return tuple(model.channels.rows)

    @staticmethod
    def line_text(channel: ChannelRowModel, counts: type[UnreadCount]) -> ChannelLineText:
        """A channel on the welcome: its name with the unread badge after it, and no line
        under it; the sidebar's channel line carries the summary."""
        badge = counts.badge(channel.unread)
        return ChannelLineText("", f"{channel.label()} {badge}" if badge else channel.label(), "",
                               channel.tooltip())


class ThreadListing(WelcomeListing):
    """The threads of the all-comms channel, in the order chosen for it."""

    TITLE = "Threads"

    def keys(self, model: SidebarModel) -> tuple[str, ...]:
        listed = model.channels.rows.get(ALL_COMMS_TARGET)
        return tuple(
            name
            for name in (listed.members if listed is not None else ())
            if name in model.threads.rows
        )
