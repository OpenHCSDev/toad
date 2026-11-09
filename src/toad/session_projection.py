"""Logical sessions expose their tab projection independently of their native screens."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Self

from agent_comms.history_views import RetiredViews
from agent_comms.registry.thread_identity import ThreadIncarnation
from textual.abstract_hooks import AbstractHooksMeta

from toad.session_tracker import OpenTab
from toad.tab_identity import TabIdentity


class SessionProjection[Navigation, Source](ABC):
    """A session supplies its tab and original thread identities to an observation."""

    identity: TabIdentity

    def tab(self, sessions: Navigation, observed: Source) -> OpenTab:
        return self.unobserved_tab()

    @abstractmethod
    def unobserved_tab(self) -> OpenTab: ...

    def original_threads(
        self, sessions: Navigation
    ) -> tuple[tuple[str, ThreadIncarnation], ...]:
        return ()


class SessionCollection[Source](metaclass=AbstractHooksMeta):
    """The open logical sessions share one projection context and retirement owner."""

    @property
    @abstractmethod
    def members(self) -> tuple[SessionProjection[Self, Source], ...]: ...

    @abstractmethod
    def views_retired(self, root: Path, retired: RetiredViews) -> None: ...
