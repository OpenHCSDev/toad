"""What Toad's welcome shows, for every frontend: its banner, and which of the sidebar
model's rows each section lists under which title. Each frontend draws them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from agent_comms.ui_model.sidebar import ChannelRowModel, SidebarModel

from toad.client.sidebar_lines import SidebarStatusLine
from toad.constants import ALL_COMMS_TARGET
from toad.setting_choices import UnreadCount
from toad.sidebar_rows import ChannelLineText


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
    """The threads of the all-comms channel: the active ones first, then the rest, each in
    the order chosen for the channel. The welcome lists only the first few, and on a bus of
    seventy stopped threads in creation order the one thread working now fell past them."""

    TITLE = "Threads"

    def keys(self, model: SidebarModel) -> tuple[str, ...]:
        listed = model.channels.rows.get(ALL_COMMS_TARGET)
        members = tuple(
            name
            for name in (listed.members if listed is not None else ())
            if name in model.threads.rows
        )
        return tuple(sorted(members, key=lambda name: not model.threads.rows[name].active))


class WelcomeLocation:
    """The welcome's location line: the attached agent's prefix, then where the welcome
    works. Textual's names the project it was started in; a remote client (Qt) names the
    bus connection it reads, its own launch directory saying nothing about that Core."""

    def location(self, app) -> str:
        raise NotImplementedError

    def location_line(self, app) -> str:
        return f"{app.agent_binding.welcome_prefix}{self.location(app)}"


class WelcomeContent:
    """What the welcome lists above its buses for what the bus last answered: nothing until
    it answers. A plain parent; the welcome draws each part through its own hooks
    (`list_section`, `say_unavailable`)."""

    def draw(self, welcome, lines) -> None:
        """Nothing has answered yet."""


@dataclass(frozen=True)
class ListedModel(WelcomeContent):
    """The bus answered: each welcome listing (channels, then threads) under its title."""

    model: SidebarModel

    def draw(self, welcome, lines) -> None:
        for listing in welcome.welcome_listings:
            welcome.list_section(lines, listing, self.model)


@dataclass(frozen=True)
class ListedFailure(WelcomeContent):
    """The bus could not be read: say why (`SidebarStatusLine.unavailable_text`)."""

    observed: object

    def draw(self, welcome, lines) -> None:
        welcome.say_unavailable(lines, SidebarStatusLine.unavailable_text(self.observed.error))
