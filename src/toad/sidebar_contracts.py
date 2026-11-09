"""Native sidebar capabilities consumed by model-row changes."""

from abc import abstractmethod
from collections.abc import Iterable, Mapping
from contextlib import AbstractContextManager

from agent_comms.display_references import ReferenceContext
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.ui_model.sidebar import ChannelRowModel
from textual.abstract_hooks import AbstractHooksMeta
from textual.dom import DOMNode


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
    """A channel group presents its model row and repaints changed thread members."""

    @abstractmethod
    def present(self, channel: ChannelRowModel) -> frozenset[str]: ...

    @abstractmethod
    def repaint_members(self, names: frozenset[str]) -> None: ...


class RelationshipMemberRows(MemberRows[str]):
    """Relationship entries map changed threads to the entries that display them."""

    @abstractmethod
    def keys_for_threads(self, names: frozenset[str]) -> frozenset[str]: ...


class NavigationRefresh(metaclass=AbstractHooksMeta):
    """The tree's navigation owner reconciles selection after rows change."""

    @abstractmethod
    def apply(self) -> None: ...


class GroupedSidebar(metaclass=AbstractHooksMeta):
    """A channel sidebar owns its groups, open-tab markers and navigation refresh."""

    groups: Mapping[str, ChannelGroupRows]
    open_views: dict[str, str]
    navigation: NavigationRefresh

    @abstractmethod
    def find_open_views(self) -> dict[str, str]: ...

    @abstractmethod
    def reconcile_members(self) -> AbstractContextManager[None]: ...


class ActivityRows(MemberRows[ThreadIncarnation], DOMNode):
    """Live channel activity supplies its own destination and changed thread rows."""

    @property
    @abstractmethod
    def references(self) -> ReferenceContext: ...

    @abstractmethod
    def channel_name(self, references: ReferenceContext) -> str: ...

    @abstractmethod
    def changed_keys(self, names: frozenset[str]) -> frozenset[ThreadIncarnation]: ...
