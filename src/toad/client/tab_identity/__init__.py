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


class TabRegistry[Entry]:
    """Where a restored tab finds its entry, or registers a new one."""

    def get(self, mode: str | None) -> Entry | None:
        raise NotImplementedError

    async def register(self, entry: Entry) -> None:
        raise NotImplementedError


class TabIdentity(DeclaredFamily, affix="Tab", discovery_package="toad.client.tab_identity"):
    @cached_property
    def mode_name(self) -> str:
        return f"{self.declared_name}-{FieldCodec.digest(self)}"

    async def restore[Entry](self, navigation: TabRegistry[Entry]) -> Entry:
        """Restore logical membership, not a succession of visible conversations."""
        entry = navigation.get(self.mode_name)
        if entry is None:
            entry = await self.entry(navigation)
            await navigation.register(entry)
        return entry

    @abstractmethod
    async def entry[Entry](self, navigation: TabRegistry[Entry]) -> Entry: ...


class SessionTabIdentity(TabIdentity):
    """An agent or mailbox tab: a session of its own."""

