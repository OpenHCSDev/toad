"""Model changes invoke the native sidebar capabilities they require."""

from __future__ import annotations

from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import (
    Iterable,
    Mapping,
)
from dataclasses import dataclass

from agent_comms.ui_model.sidebar import ChannelRowModel

from toad.sidebar_contracts import ActivityRows, GroupedSidebar, MemberRows, RelationshipMemberRows


class SidebarChange(ABC):
    """The changed model rows choose which native rows need work."""

    @abstractmethod
    def apply_comms(self, sidebar: GroupedSidebar, rows: Mapping[str, ChannelRowModel]) -> None:
        ...

    @abstractmethod
    def apply_welcome(self, channel_list: MemberRows[str], thread_list: MemberRows[str]) -> None:
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

    def apply_welcome(self, channel_list: MemberRows[str], thread_list: MemberRows[str]) -> None:
        channel_list.sync_members(frozenset(channel_list.member_keys))
        thread_list.sync_members(frozenset(thread_list.member_keys))

    def apply_relationships(self, groups: Iterable[RelationshipMemberRows]) -> None:
        for group in groups:
            group.sync_members(frozenset(group.member_keys))

    def apply_activity(self, view: ActivityRows) -> None:
        view.call_next(view.sync_members, frozenset(view.member_keys))


@dataclass(frozen=True)
class ChangedChannels(SidebarChange):
    names: frozenset[str]

    def apply_comms(self, sidebar: GroupedSidebar, rows: Mapping[str, ChannelRowModel]) -> None:
        with sidebar.reconcile_members():
            for name in self.names:
                group = sidebar.groups.get(name)
                if group is not None:
                    group.sync_members(group.present(rows[name]))

    def apply_welcome(self, channel_list: MemberRows[str], thread_list: MemberRows[str]) -> None:
        channel_list.sync_members(self.names)
        # A changed channel can change the welcome thread list's order.
        thread_list.sync_members(frozenset())

    def apply_relationships(self, groups: Iterable[RelationshipMemberRows]) -> None:
        pass

    def apply_activity(self, view: ActivityRows) -> None:
        if view.channel_name(view.references) in self.names:
            view.call_next(view.sync_members, frozenset(view.member_keys))


@dataclass(frozen=True)
class ChangedThreads(SidebarChange):
    names: frozenset[str]

    def apply_comms(self, sidebar: GroupedSidebar, rows: Mapping[str, ChannelRowModel]) -> None:
        for group in sidebar.groups.values():
            group.repaint_members(self.names)

    def apply_welcome(self, channel_list: MemberRows[str], thread_list: MemberRows[str]) -> None:
        thread_list.sync_members(self.names)

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
