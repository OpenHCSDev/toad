"""Durable tab identities; Textual names are a projection of the wire identity."""

from __future__ import annotations

from abc import abstractmethod
from functools import cached_property

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import FieldCodec


class TabTargetGone(Exception):
    def __init__(self, identity: TabIdentity, reason: str) -> None:
        self.identity = identity
        self.reason = reason
        super().__init__(f"{identity}: {reason}")


class TabNotDrawnHere(LookupError):
    """This frontend declares no view for the tab's kind (Qt draws no file preview). The tab
    stays saved for a frontend that draws it; it is not a target that is gone."""

    def __init__(self, identity: TabIdentity) -> None:
        self.identity = identity
        super().__init__(f"No view in this frontend shows {identity}")


class TabIdentity(DeclaredFamily, affix="Tab", discovery_package="toad.client.tab_identity"):
    @cached_property
    def mode_name(self) -> str:
        return f"{self.declared_name}-{FieldCodec.digest(self)}"

    async def restore(self, navigation: object) -> object:
        """Restore logical membership, not a succession of visible conversations."""
        entry = navigation.get(self.mode_name)
        if entry is None:
            entry = await self.entry(navigation)
            await navigation.register(entry)
        return entry

    @abstractmethod
    async def entry(self, navigation: object) -> object: ...

    def declarations(self) -> tuple[object, ...]:
        """What this tab shows, most specific first: its kind and that kind's bases."""
        return type(self).__mro__


class SessionTabIdentity(TabIdentity):
    """An agent or mailbox tab: a session of its own."""

