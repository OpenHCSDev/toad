"""History opened from a resident welcome view or from a durable agent tab."""

from abc import abstractmethod
from dataclasses import dataclass

from agent_comms.declared_family import DeclaredFamily

from toad.constants import WELCOME
from toad.tab_identity import SessionTabIdentity


class HistoryOrigin(DeclaredFamily, affix="HistoryOrigin"):
    @property
    @abstractmethod
    def mode_name(self) -> str: ...

    @abstractmethod
    async def restore(self, navigation) -> None: ...


@dataclass(frozen=True)
class WelcomeHistoryOrigin(HistoryOrigin):
    @property
    def mode_name(self) -> str:
        return WELCOME

    async def restore(self, navigation) -> None:
        await navigation.app.select_session(WELCOME)


@dataclass(frozen=True)
class SessionHistoryOrigin(HistoryOrigin):
    identity: SessionTabIdentity

    @property
    def mode_name(self) -> str:
        return self.identity.mode_name

    async def restore(self, navigation) -> None:
        if navigation.get(self.mode_name) is None:
            await self.identity.restore(navigation)
