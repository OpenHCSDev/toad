"""Model changes invoke the native sidebar capabilities they require."""

from __future__ import annotations

from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from dataclasses import dataclass

from agent_comms.ui_model.sidebar import ChannelRowModel

from toad.sidebar_contracts import ActivityRows, GroupedSidebar, RelationshipMemberRows


class SidebarChange(ABC):
    """The changed model rows choose which native rows need work."""

    def sync_sidebar(
        self,
        sidebar: GroupedSidebar,
        rows: Mapping[str, ChannelRowModel],
        *,
        reorder: bool,
        full_redraw: Callable[[], None],
    ) -> None:
        """Apply this change to a grouped sidebar: wholesale changes take ``full_redraw``."""
        full_redraw()

    @abstractmethod
    def apply_comms(self, sidebar: GroupedSidebar, rows: Mapping[str, ChannelRowModel]) -> None:
        ...

    @abstractmethod
    def apply_relationships(self, groups: Iterable[RelationshipMemberRows]) -> None:
        ...

    @abstractmethod
    def apply_activity(self, view: ActivityRows) -> None:
        ...

    def apply_navigation(self, sidebar: GroupedSidebar) -> None:
        sidebar.navigation.apply()


class AllSidebarRows(SidebarChange):
    def apply_comms(self, sidebar: GroupedSidebar, rows: Mapping[str, ChannelRowModel]) -> None:
        sidebar.open_views = sidebar.find_open_views()
        with sidebar.reconcile_members():
            for name, group in sidebar.groups.items():
                group.present(rows[name])
                group.sync_members(frozenset(group.member_keys))

    def apply_relationships(self, groups: Iterable[RelationshipMemberRows]) -> None:
        for group in groups:
            group.sync_members(frozenset(group.member_keys))

    def apply_activity(self, view: ActivityRows) -> None:
        view.call_next(view.sync_members, frozenset(view.member_keys))


class PartialSidebarChange(SidebarChange):
    """A change touching only a subset of rows; when order is unchanged, skip a full redraw."""

    def sync_sidebar(
        self,
        sidebar: GroupedSidebar,
        rows: Mapping[str, ChannelRowModel],
        *,
        reorder: bool,
        full_redraw: Callable[[], None],
    ) -> None:
        if reorder:
            full_redraw()
        else:
            self.apply_comms(sidebar, rows)


@dataclass(frozen=True)
class ChangedChannels(PartialSidebarChange):
    names: frozenset[str]

    def apply_comms(self, sidebar: GroupedSidebar, rows: Mapping[str, ChannelRowModel]) -> None:
        with sidebar.reconcile_members():
            for name in self.names:
                group = sidebar.groups.get(name)
                if group is not None:
                    group.sync_members(group.present(rows[name]))

    def apply_relationships(self, groups: Iterable[RelationshipMemberRows]) -> None:
        pass

    def apply_activity(self, view: ActivityRows) -> None:
        if view.channel_name(view.references) in self.names:
            view.call_next(view.sync_members, frozenset(view.member_keys))


@dataclass(frozen=True)
class ChangedThreads(PartialSidebarChange):
    names: frozenset[str]

    def apply_comms(self, sidebar: GroupedSidebar, rows: Mapping[str, ChannelRowModel]) -> None:
        for group in sidebar.groups.values():
            group.repaint_members(self.names)

    def apply_relationships(self, groups: Iterable[RelationshipMemberRows]) -> None:
        for group in groups:
            changed = group.keys_for_threads(self.names)
            if changed:
                group.sync_members(changed=changed)

    def apply_activity(self, view: ActivityRows) -> None:
        changed = view.changed_keys(self.names)
        if changed:
            view.call_next(view.sync_members, changed)

    def apply_navigation(self, sidebar: GroupedSidebar) -> None:
        pass
