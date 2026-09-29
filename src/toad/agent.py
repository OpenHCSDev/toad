from toad.agent_presentation import LocalAgentPresentation
from toad.conversation_turn import NoTurn
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from agent_comms.thread_presentation import ThreadPresentation

from textual.content import Content
from textual.message import Message


class AgentReady(Message):
    """Agent is ready."""

    def __init__(self, *, reconnected: bool = False):
        super().__init__()
        self.reconnected = reconnected


@dataclass
class AgentFail(Message):
    """Agent failed to start."""

    message: str
    details: str = ""
    help: str = "fail"


class AgentBase(ABC):
    """Base class for an 'agent'."""

    def __init__(self, project_root: Path) -> None:
        self.project_root_path = project_root
        self.presentation = LocalAgentPresentation(self)

    ready = False

    @property
    def current_turn(self):
        return NoTurn()

    def attach_surface(self, surface):
        pass

    async def retire_surface(self, surface):
        await self.stop()

    async def get_thread_presentation(self) -> ThreadPresentation | None:
        """Agents without a coordination identity have no observed thread status."""
        return None

    @abstractmethod
    async def send_prompt(self, prompt: str) -> str | None:
        """Send a prompt; return its stop reason."""

    async def set_mode(self, mode_id: str) -> str | None:
        """Select a mode; return its stop reason."""

    async def cancel(self) -> bool:
        """Cancel the active prompt if supported."""
        return False

    async def set_model(self, model_id: str) -> str | None:
        return "This agent does not support model selection"

    async def set_session_name(self, name: str) -> None:
        """Set the session name.

        Args:
            name: New name for the session.
        """

    def get_info(self) -> Content:
        return Content("")

    async def stop(self) -> None:
        """Stop the agent (gracefully exit the process)"""
