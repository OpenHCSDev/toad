"""The decisions a sidebar tree's lines make, owned once for both frontends.

A Qt line is a `QTreeWidgetItem` (or a widget over one) and a Textual line is a widget;
each draws, but what a line shows, what activating it does and what a group remembers are
declared here, and both frontends' lines inherit them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from toad.client.menu_entry import MenuEntry
from toad.client.relationship_row_menu import menu_entries_for_row
from toad.command_catalog import CommandCatalog


class DetailedLine:
    """A line of two rows: its title after its status prefix (the unread badge), then its
    own quieter detail indented under it. Textual's `DetailedRow` and Qt's `SidebarItem`
    draw it."""

    detail_indent: ClassVar[int] = 2
    """Cells the detail row is indented under the title."""

    @classmethod
    def detail_text(cls, detail: str) -> str:
        """The detail row as drawn: indented under the title."""
        return f"{' ' * cls.detail_indent}{detail}"

    @staticmethod
    def status_prefix(badge: str) -> str:
        """What precedes the title on the first row: the badge and one space, or nothing."""
        return f"{badge} " if badge else ""


class MemberGroupLine:
    """A line heading a group of rows: activating it opens or closes the members, and the
    group may then remember how the reader left it. Textual's `SidebarGroup` and Qt's
    `SidebarSection` inherit the decision; each says how its members show."""

    @property
    def members_open(self) -> bool:
        raise NotImplementedError

    def show_members(self, shown: bool) -> None:
        raise NotImplementedError

    def accepts_toggle(self) -> bool:
        """Whether the group can open or close now (Textual's while it holds members)."""
        return True

    def toggle_members(self) -> None:
        if self.accepts_toggle():
            self.show_members(not self.members_open)
            self.members_toggled()

    def members_toggled(self) -> None:
        """The reader opened or closed the group; a group that remembers it overrides this."""


class WelcomeSectionLine(MemberGroupLine):
    """A welcome section: it opens as the shared sidebar state says
    (`SidebarState.welcome_section_open`) and records what the reader leaves it as, so it
    stays put however often the welcome is drawn again. Textual's `WelcomeSection` and Qt's
    `OpenSection`."""

    @property
    def section_title(self) -> str:
        raise NotImplementedError

    @property
    def sidebar_state(self):
        raise NotImplementedError

    def opens(self) -> bool:
        return self.sidebar_state.welcome_section_open(self.section_title)

    def members_toggled(self) -> None:
        self.sidebar_state.set_welcome_section_open(self.section_title, self.members_open)


class SidebarStatusLine(DetailedLine):
    """The sidebar's status: an observation status (`Connecting…`, `Behind`) or why the bus
    could not be read, its first line as the title and the rest as the detail under it.
    Textual's `SidebarStatus`, Qt's `StatusSection` and `UnavailableSection`, and the
    failed sidebar state's text all read it here."""

    key: ClassVar[str] = "__status__"

    @staticmethod
    def unavailable_text(error: BaseException) -> str:
        """What a sidebar or welcome says while the bus cannot be read: one persistent state,
        the same however many reopen attempts (connection.ObservationRetry) fail behind it."""
        return f"Comms unavailable; reconnecting\n{error}"

    @staticmethod
    def status_rows(text: str) -> tuple[str, str]:
        """The status as its title row and the detail under it."""
        title, _, detail = text.partition("\n")
        return title, detail


class TargetLine:
    """A line that opens a navigation target (a channel or a thread): it is keyed by the
    target's name and opens its members as the target says by default. Textual's
    `CommsRow` and Qt's `ConversationRow`.

    Its menu is declared here and nowhere else: `menu_entries` is what a right-click or a
    held finger offers in every frontend, and each toolkit only draws the entries
    (Textual's `ActionMenu.offer`, Qt's menu panel). A toolkit line that defined its own
    `menu_entries`, or built a menu by calling the owners below, fails
    `tests/model/test_menu_owners.py`."""

    target: object

    @property
    def target_name(self) -> str:
        return self.target.name

    def opens_expanded(self) -> bool:
        return self.target.expanded_by_default

    @property
    def menu_tree(self) -> LineMenuTree:
        """The tree the line is drawn in, which supplies the context its commands run in."""
        raise NotImplementedError

    async def menu_entries(self) -> tuple[MenuEntry, ...]:
        """The commands the line's target applies, in its tree's context."""
        return await CommandCatalog.pointer_menu(self.menu_tree.row_menu_context(self))


class LineMenuTree:
    """A tree of `TargetLine`s: the context a line's commands run in, and how a Comms
    relationship opens. Textual's sidebar trees and Qt's `ConversationRows` and
    `QtThreadCommsPanel` answer it."""

    def row_menu_context(self, line: TargetLine):
        """The command context for `line`'s target in this tree."""
        raise NotImplementedError

    def relationship_opener(self, line: RelationshipLine) -> Callable[[], object]:
        """What Open runs for a relationship line, captured when the menu opens."""
        raise NotImplementedError

    def copy_name(self, name: str) -> None:
        raise NotImplementedError


class RelationshipLine(TargetLine):
    """A Comms relationship (Textual's `RelationshipRow`, Qt's `QtRelationshipItem`): its
    menu is Open while the relationship is available, and Copy name."""

    available: bool

    async def menu_entries(self) -> tuple[MenuEntry, ...]:
        tree = self.menu_tree
        return menu_entries_for_row(
            target_name=self.target_name,
            copy=tree.copy_name,
            open_callback=tree.relationship_opener(self) if self.available else None,
        )


class HeaderLine:
    """A group's header line: its title, elided into the room the other stretches leave;
    then its unread badge, which always shows, one cell after the title; then the group's
    control (a channel's member order). Textual's `GroupHeaderLine` and Qt's
    `HeaderLineControl`; a press on the title opens the line."""

    @staticmethod
    def badge_stretch(badge: str) -> str:
        return f" {badge}" if badge else ""

    @staticmethod
    def control_stretch(label: str) -> str:
        return f" {label}"


class RowTree:
    """A sidebar's tree of lines: members indent under their group's line, and its
    scrollbar is one cell wide so a narrow sidebar keeps its text. Textual's `TargetTree`
    and Qt's `ConversationRows`."""

    member_indent: ClassVar[int] = 2
    scrollbar_cells: ClassVar[int] = 1


class BusChoiceLine:
    """A bus a listing offers (a held bus, or a tailnet peer to ask): the line names it as
    the choice does, and choosing it does what the choice says. Textual's `BusOption` and
    Qt's `BusRow`."""

    choice: object

    def line_label(self) -> str:
        return self.choice.label()

    def choose(self, host) -> None:
        self.choice.chosen(host)

    def line_actions(self, listing) -> tuple:
        """What a held finger or a right click offers: the choice's own (forgetting a saved
        bus)."""
        return self.choice.held_actions(listing)
