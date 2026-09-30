from toad.agent_presentation import LocalAgentPresentation
from toad.acp.status import StopReason
from toad.conversation_turn import NoTurn
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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
class AgentFail(Message, ABC):
    """Agent failed to start."""

    message: str
    details: str = ""
    @abstractmethod
    async def explain(self, view): ...


class HelpAgentFail(AgentFail):
    @property
    @abstractmethod
    def help_text(self) -> str: ...

    async def explain(self, view):
        from toad.widgets.markdown_note import MarkdownNote
        await view.post(MarkdownNote(self.help_text))


class UnsupportedResumeAgentFail(HelpAgentFail):
    help_text = """## Agent does not support resume

The agent or ACP adapter does not support resuming sessions.

Try updating to see if support has been added.

- Exit the app, and run `toad` again
- Select the agent and hit ENTER
- Click the dropdown, select "Update" or "Install" again
- Repeat the process to update the ACP adapter (if required)

If that fails, ask for help in [Discussions](https://github.com/batrachianai/toad/discussions)!
"""


@dataclass
class LogAgentFail(AgentFail):
    log_path: Path = field(kw_only=True)

    async def explain(self, view):
        from urllib.parse import quote
        from toad.widgets.agent_response import AgentResponse
        from toad.widgets.message_filter import OtherCategory
        link = AgentResponse(f"[Open ACP log]({quote(str(self.log_path))})",
                             show_divider=False, category=OtherCategory)
        link.add_class("-error-log-link")
        await view.post(link)


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

    async def get_message_notifications(self, references):
        """Uncoordinated agents have no durable wire notification source."""
        return {}

    async def observe_thread_presentation(self, presentation: ThreadPresentation | None) -> None:
        """Consume a published canonical change; unmanaged agents need no binding."""

    @abstractmethod
    async def send_prompt(self, prompt: str) -> type[StopReason] | None:
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
