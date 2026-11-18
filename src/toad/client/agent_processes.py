"""Whether this platform can run agent processes, decided once for every frontend.

A desktop starts an ACP agent as a child process. Android's app sandbox runs no agent
process, so a launch there attaches no agent, and a session that would start one opens
without it and says why. The launch (`launch_binding`) and the unbound view's agent start
(`SessionSources.create_agent`) both ask this, not the platform.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from collections.abc import Callable

from toad.client.agents import read_agents
from toad.launch_binding import AgentAttached, AgentBinding, NoAgent


class UnknownAgent(LookupError):
    """No configured agent answers to the requested name."""

    def __init__(self, requested: str, known: tuple[str, ...]) -> None:
        super().__init__(f"Unknown agent {requested!r}. Known agents: {', '.join(known)}")
        self.requested = requested
        self.known = known


class AgentProcesses(ABC):
    """This platform's answer to "may an agent process start here"."""

    @staticmethod
    def of_platform() -> AgentProcesses:
        """Android's Python runs inside the app sandbox, with no agent processes."""
        return NoAgentProcesses() if hasattr(sys, "getandroidapilevel") else SpawnsAgentProcesses()

    @abstractmethod
    async def launch_binding(self, requested: str) -> AgentBinding:
        """The launch's agent for the name the user asked for (empty: none)."""

    @abstractmethod
    def start(self, create: Callable[[], None], refused: Callable[[str], None]) -> None:
        """Start an agent process through `create`, or say why it cannot start here."""


class SpawnsAgentProcesses(AgentProcesses):
    async def launch_binding(self, requested: str) -> AgentBinding:
        if not requested:
            return NoAgent()
        wanted = requested.lower()
        agents = await read_agents()
        for agent in agents.values():
            if wanted in (agent.short_name.lower(), agent.identity.lower()):
                return AgentAttached(agent)
        raise UnknownAgent(requested, tuple(sorted(
            f"{agent.short_name} ({agent.identity})" if agent.short_name else agent.identity
            for agent in agents.values())))

    def start(self, create: Callable[[], None], refused: Callable[[str], None]) -> None:
        create()


class NoAgentProcesses(AgentProcesses):
    async def launch_binding(self, requested: str) -> AgentBinding:
        return NoAgent()

    def start(self, create: Callable[[], None], refused: Callable[[str], None]) -> None:
        refused("This device runs no agent processes; open the session from a desktop.")
