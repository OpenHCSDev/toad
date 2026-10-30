"""History opened from a resident welcome view or from a durable agent tab."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily

from toad.constants import WELCOME
from toad.tab_identity import SessionTabIdentity

if TYPE_CHECKING:
    from toad.session_navigation import SessionNavigation
    from toad.session_scope import SessionScope


class HistoryOrigin(DeclaredFamily, affix="HistoryOrigin"):
    @property
    @abstractmethod
    def mode_name(self) -> str: ...

    @abstractmethod
    async def restore(self, navigation: SessionNavigation) -> SessionScope: ...


@dataclass(frozen=True)
class WelcomeHistoryOrigin(HistoryOrigin):
    @property
    def mode_name(self) -> str:
        return WELCOME

    async def restore(self, navigation: SessionNavigation) -> SessionScope:
        source = await navigation.app.prepare_session(WELCOME)
        await source.prepare_history_origin()
        return source


@dataclass(frozen=True)
class SessionHistoryOrigin(HistoryOrigin):
    identity: SessionTabIdentity

    @property
    def mode_name(self) -> str:
        return self.identity.mode_name

    async def restore(self, navigation: SessionNavigation) -> SessionScope:
        return await self.identity.history_source(navigation)
