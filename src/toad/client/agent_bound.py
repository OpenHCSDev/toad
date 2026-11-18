"""The agent-binding half of `ConversationSessionBinding`.

Both backends attach exactly one `AgentConnection` to a conversation view and react when
that attachment or its ready state changes. The three methods in the chain —
`bind_agent` / `apply_bound_agent` / `agent_connected` — live here as a toolkit-neutral
base: the concrete attachment write is shared (`bind_agent` → store + `attach_view`);
projecting and announcing the agent are backend hooks because they touch backend-specific
status widgets and app observers.

`AgentBoundConversation` is the plain base every conversation view inherits. The
companion `ObservedAgentBinding` mixin layers an `ObservedField[AgentConnection]`
descriptor on top for backends that don't have their own reactive attachment (Qt uses
it; Textual's `Conversation` keeps its `var[AgentConnection]` for now — follow-up PR
unifies the storage).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

from toad.client.observed_field import ObservedField


if TYPE_CHECKING:
    from toad.agent_binding import AgentConnection
    from toad.agent import AgentBase


class AgentBoundConversation(ABC):
    """A conversation view that binds to exactly one agent connection."""

    def bind_agent(self, agent: "AgentConnection") -> None:
        """Attach this view to an agent connection as its presenter."""
        self._store_agent_binding(agent)
        agent.attach_view(self)

    @property
    @abstractmethod
    def bound_agent(self) -> "AgentConnection":
        """The agent on this view: its live connection, or `NoAgentConnection` before one
        is bound."""

    @abstractmethod
    def _store_agent_binding(self, agent: "AgentConnection") -> None:
        """Persist the agent reference on the view; backends use their own storage."""

    @abstractmethod
    def apply_bound_agent(self, agent: "AgentBase") -> None:
        """Project `agent`'s model/context/goal state onto the bound view."""

    @abstractmethod
    def agent_connected(self, agent: "AgentBase") -> None:
        """Flash a connection notice and record a usage milestone."""


class ObservedAgentBinding(AgentBoundConversation):
    """Agent-binding storage as an `ObservedField`, for backends that want change watchers.

    Subclasses register a watcher via `on_agent_binding_change(callback)` to re-render on
    live reconnect. Textual's `Conversation` has its own reactive `var` and does not
    inherit this mixin yet.
    """

    agent_binding: ObservedField["AgentConnection"]
    """Override on each subclass — placeholder for the ObservedField descriptor."""

    def _store_agent_binding(self, agent: "AgentConnection") -> None:
        self.agent_binding = agent  # type: ignore[assignment]

    @property
    def bound_agent(self) -> "AgentConnection":
        """The stored `agent_binding`: `NoAgentConnection` until a live agent binds."""
        return self.agent_binding

    def on_agent_binding_change(
        self, callback: Callable[["AgentConnection", "AgentConnection"], None]
    ) -> Callable[[], None]:
        """Register a watcher fired on every agent-binding change; returns an unregister."""
        descriptor = type(self).__dict__["agent_binding"]
        return descriptor.watch(self, callback)
