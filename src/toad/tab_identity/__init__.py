"""Durable tab identities; Textual names are a projection of the wire identity."""

from abc import abstractmethod
from functools import cached_property

from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldCodec


class TabTargetGone(Exception):
    def __init__(self, identity: "TabIdentity", reason: str) -> None:
        self.identity = identity
        self.reason = reason
        super().__init__(f"{identity}: {reason}")


class TabIdentity(DeclaredFamily, affix="Tab", discovery_package="toad.tab_identity"):
    @cached_property
    def mode_name(self) -> str:
        return f"{self.declared_name}-{FieldCodec.digest(self)}"

    @abstractmethod
    async def restore(self, navigation) -> None: ...


class SessionTabIdentity(TabIdentity):
    """An agent or mailbox tab can own history tabs."""

