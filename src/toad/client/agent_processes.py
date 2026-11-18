"""Whether agent processes start under this client's Core connection, for every frontend.

An ACP agent is a child of the client, and its prompts are written under the local route's
maintenance gate, so only a connection to this machine's own bus (`LocalCoreConnection`,
the TUI's and desktop Qt's default) spawns one. A client reaching Core through a UI
profile, as Android always does, holds no local route: a launch there attaches no agent
(`AgentBinding.launched` refuses the name), and a session that would start one opens
without it and says why (`SessionSources.create_agent`). Both ask the connection's member,
never the platform.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class AgentProcesses(ABC):
    """A connection's answer to "may an agent process start here"."""

    @abstractmethod
    def start[T](self, create: Callable[[], T], refused: Callable[[str], T]) -> T:
        """Start an agent process through `create`, or say through `refused` why it cannot."""


class SpawnsAgentProcesses(AgentProcesses):
    def start[T](self, create: Callable[[], T], refused: Callable[[str], T]) -> T:
        return create()


class NoAgentProcesses(AgentProcesses):
    reason = ("This client reaches Core through a UI profile, so it starts no agent; "
              "start the session where Core runs.")

    def start[T](self, create: Callable[[], T], refused: Callable[[str], T]) -> T:
        return refused(self.reason)
