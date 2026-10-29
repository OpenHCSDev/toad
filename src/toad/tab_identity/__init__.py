"""Durable tab identities; Textual names are a projection of the wire identity."""

from __future__ import annotations

from abc import abstractmethod
from functools import cached_property
from typing import TYPE_CHECKING

from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldCodec

if TYPE_CHECKING:
    from toad.session_entry import SessionEntry


class TabTargetGone(Exception):
    def __init__(self, identity: "TabIdentity", reason: str) -> None:
        self.identity = identity
        self.reason = reason
        super().__init__(f"{identity}: {reason}")


class TabIdentity(DeclaredFamily, affix="Tab", discovery_package="toad.tab_identity"):
    @cached_property
    def mode_name(self) -> str:
        return f"{self.declared_name}-{FieldCodec.digest(self)}"

    async def restore(self, navigation) -> SessionEntry:
        """Restore logical membership, not a succession of visible conversations."""
        entry = navigation.get(self.mode_name)
        if entry is None:
            entry = await self.entry(navigation)
            await navigation.register(entry)
        return entry

    @abstractmethod
    async def entry(self, navigation) -> SessionEntry: ...


class SessionTabIdentity(TabIdentity):
    """An agent or mailbox tab can own history tabs."""

    async def history_source(self, navigation):
        """An ACP session must establish its actual identity before routing history."""
        entry = await self.restore(navigation)
        await navigation.app.select_session(entry.mode)
        await navigation.app.workspace_sessions.require(entry.mode).wait_content_ready()
        return navigation.app.workspace_sessions.require(entry.mode)
