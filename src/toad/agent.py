from toad.agent_presentation import LocalAgentPresentation
from toad.acp.status import StopReason
from toad.conversation_turn import NoTurn
from abc import ABC, abstractmethod
from pathlib import Path
from agent_comms.thread_presentation import ThreadPresentation
from toad.core.events import CoreEventStream



class AgentBase(ABC):
    """Base class for an 'agent'."""

    def __init__(self, project_root: Path) -> None:
        self.project_root_path = project_root
        self.events = CoreEventStream(self)
        self.presentation = LocalAgentPresentation(self)
        from toad.acp.agent_configuration import AgentConfiguration
        self.configuration = AgentConfiguration(self)

    ready = False

    @property
    def current_turn(self):
        return NoTurn()

    def attach_surface(self, binding):
        binding.close()

    async def retire_surface(self, surface):
        await self.stop()

    async def get_thread_presentation(self) -> ThreadPresentation | None:
        """Agents without a coordination identity have no observed thread status."""
        return None

    async def get_message_notifications(self, references):
        """Uncoordinated agents have no durable wire notification source."""
        return {}

    async def observe_thread_presentation(self, presentation: ThreadPresentation | None) -> None:
        """Consume a published canonical change; unmanaged agents need no binding."""

    @abstractmethod
    async def send_prompt(self, prompt: str) -> type[StopReason] | None:
        """Send a prompt; return its stop reason."""

    @property
    def available_modes(self):
        return ()

    @property
    def current_mode(self):
        return None

    async def set_mode(self, mode_id: str) -> str | None:
        return "This agent does not support mode selection"

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

    def get_info(self) -> str:
        return ""

    async def stop(self) -> None:
        """Stop the agent (gracefully exit the process)"""
