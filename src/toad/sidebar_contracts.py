"""Native sidebar capabilities consumed by model-row changes."""

from abc import abstractmethod
from collections.abc import Iterable, Mapping
from contextlib import AbstractContextManager

from agent_comms.messaging.display_references import ReferenceContext
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.ui_model.sidebar import ChannelRowModel
from metaclass_registry import AbstractHooksMeta


class TargetRows[Row](metaclass=AbstractHooksMeta):
    """A group supplies the native rows displaying one destination name."""

    @abstractmethod
    def rows_for_target(self, name: str) -> tuple[Row, ...]: ...


class MemberRows[Key](metaclass=AbstractHooksMeta):
    """A keyed view publishes the members it shows and reconciles changed members."""

    @property
    @abstractmethod
    def member_keys(self) -> Iterable[Key]: ...

    @abstractmethod
    def sync_members(self, changed: frozenset[Key]) -> None: ...


class ChannelGroupRows(MemberRows[str]):
    """A channel group presents its model row and repaints changed thread members.

    `channel` is the model row the group last presented: an `UnpaintedChannel` until the
    first, in both frontends (Qt's group held `None` there and asked whether it had one)."""

    channel: ChannelRowModel

    def present(self, channel: ChannelRowModel) -> frozenset[str]:
        """Paint the header and return the members whose channel pin changed. One sequence
        for both frontends: the row paints the channel, the sort control takes its order,
        and the frontend does what is its own with what changed (`header_presented`)."""
        previous, self.channel = self.channel, channel
        self.row.present_channel(channel, counts=self.unread_counts)
        self.sort_choice.update_order(channel.order)
        self.header_presented(previous, channel)
        return previous.pinned_members ^ channel.pinned_members

    @property
    @abstractmethod
    def unread_counts(self):
        """The `sidebar.unread_counts` setting the header's badge is drawn by."""

    def header_presented(self, previous: ChannelRowModel, channel: ChannelRowModel) -> None:
        """What this frontend does of its own once the header shows `channel`: nothing,
        unless it animates a new message or repaints a painted stretch."""

    def repaint_members(self, names: frozenset[str]) -> None:
        """Repaint this group's shown rows among the changed threads `names`, from the model
        the sidebar shows. Membership is the channel row's fact: added and removed threads
        change its `members` and reach `sync_members` as a channel change. One sequence for
        both frontends (`KeyedRows.update_row` paints a row in each)."""
        if not self.accepts_members():
            return
        threads = self.sidebar.model_state.shown.threads.rows
        for name in self.rows.keys() & names & threads.keys():
            self.update_row(name, self.rows[name])

    # `accepts_members` (whether this group's rows may be painted from the model now) is
    # each frontend's group's own: Textual's `SidebarGroup` answers it for every group and
    # `ChannelGroup` narrows that with `super()`. It is not declared here: this class comes
    # before `SidebarGroup` in `ChannelGroup`'s order, so an abstract declaration here was
    # what that `super()` reached, it answered nothing, and no member row was ever painted
    # (2026-11-22, caught by tests/textual: "the CLI's row not reached").


class RelationshipMemberRows(MemberRows[str]):
    """Relationship entries map changed threads to the entries that display them."""

    @abstractmethod
    def keys_for_threads(self, names: frozenset[str]) -> frozenset[str]: ...


class NavigationRefresh(metaclass=AbstractHooksMeta):
    """The tree's navigation owner reconciles selection after rows change."""

    @abstractmethod
    def apply(self) -> None: ...


class FindsOpenViews:
    """Which open tab shows each thread of this sidebar's bus; the first tab claims it.
    Textual's `CommsSidebar` and Qt's `Sidebar`: a row's menu runs its commands in that
    tab's mode (`NavigationTarget.menu_context`)."""

    def find_open_views(self) -> dict[str, str]:
        app = self.app
        threads = self.model_state.shown.threads.rows
        views: dict[str, str] = {}
        for details in app.session_tracker.ordered_sessions:
            screen = app.session_navigation.source(details.mode_name)
            if screen is None:
                continue
            name = screen.thread_identity.thread_name()
            if (name in threads and name not in views
                    and screen.belongs_to_wire(self.navigation_root)):
                views[name] = details.mode_name
        return views


class GroupedSidebar(metaclass=AbstractHooksMeta):
    """A channel sidebar owns its groups, open-tab markers and navigation refresh."""

    groups: Mapping[str, ChannelGroupRows]
    open_views: dict[str, str]
    navigation: NavigationRefresh

    @abstractmethod
    def find_open_views(self) -> dict[str, str]: ...

    @abstractmethod
    def reconcile_members(self) -> AbstractContextManager[None]: ...


class ActivityRows(MemberRows[ThreadIncarnation]):
    """Live channel activity supplies its own destination and changed thread rows."""

    @property
    @abstractmethod
    def references(self) -> ReferenceContext: ...

    @abstractmethod
    def channel_name(self, references: ReferenceContext) -> str: ...

    @abstractmethod
    def changed_keys(self, names: frozenset[str]) -> frozenset[ThreadIncarnation]: ...
