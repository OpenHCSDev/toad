"""The connection's initialization state owns reuse and advertised capabilities."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from acp import schema


class AgentInitialization:
    """A connection that has not completed its SDK handshake."""

    @property
    def capabilities(self) -> schema.AgentCapabilities:
        return schema.AgentCapabilities()

    @property
    def auth_methods(self) -> tuple[
        schema.EnvVarAuthMethod | schema.TerminalAuthMethod | schema.AuthMethodAgent, ...
    ]:
        return ()

    @property
    def supports_close(self) -> bool:
        return False

    async def initialize(self, request: Callable[[], Awaitable[None]]) -> None:
        await request()


@dataclass(frozen=True)
class InitializedAgent(AgentInitialization):
    """The original SDK response, retained once by its connection."""

    response: schema.InitializeResponse

    @property
    def capabilities(self) -> schema.AgentCapabilities:
        return self.response.agent_capabilities or super().capabilities

    @property
    def auth_methods(self) -> tuple[
        schema.EnvVarAuthMethod | schema.TerminalAuthMethod | schema.AuthMethodAgent, ...
    ]:
        return tuple(self.response.auth_methods or ())

    @property
    def supports_close(self) -> bool:
        lifecycle = self.capabilities.session_capabilities
        return bool(lifecycle and lifecycle.close)

    async def initialize(self, request: Callable[[], Awaitable[None]]) -> None:
        """The ordinary handshake reuses this connection's completed response."""
