from __future__ import annotations

from asyncio import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

import rich.repr
from agent_comms.acp_extension import (
    AgentCommsUpdate,
    QueueScope,
)
from agent_comms.routing import MessageRoute
from textual.message import Message

from toad.acp import protocol
from toad.acp.encode_tool_call_id import encode_tool_call_id
from toad.answer import Answer

from .attachment_presentation import CursorPresentation, QueuePresentation

if TYPE_CHECKING:
    from textual.content import Content

    from toad.acp.agent import Mode, Model
    from toad.widgets.terminal_tool import ToolState


class AgentMessage(Message):
    """Base class for agent messages."""


class InputDispositionsChanged(AgentMessage):
    """Invalidate delivery display; the producer ledger owns its contents."""


class RejectedSessionUpdate(AgentMessage):
    """Invalid ACP input was logged and excluded from the conversation."""


@dataclass
class McpClientStopped(AgentMessage):
    """The owning connection stopped; its live projection is no longer valid."""

    agent: object


@dataclass
class Thinking(AgentMessage):
    type: str
    text: str


@dataclass
class UpdateStatusLine(AgentMessage):
    status_line: str | Content


@dataclass
class Update(AgentMessage):
    type: str
    text: str
    route: MessageRoute | None = None


@dataclass
class UserMessage(Message):
    type: str
    text: str


@dataclass
@rich.repr.auto
class RequestPermission(AgentMessage):
    options: list[protocol.PermissionOption]
    tool_call: protocol.ToolCallUpdatePermissionRequest
    result_future: Future[Answer | None]


@dataclass
class Plan(AgentMessage):
    entries: list[protocol.PlanEntry]


@dataclass
class ToolCall(AgentMessage):
    tool_call: protocol.ToolCall

    @property
    def tool_id(self) -> str:
        """An id suitable for use as a TCSS ID."""
        return encode_tool_call_id(self.tool_call["toolCallId"])


@dataclass
class ToolCallUpdate(AgentMessage):
    tool_call: protocol.ToolCall
    update: protocol.ToolCallUpdate

    @property
    def tool_id(self) -> str:
        """An id suitable for use as a TCSS ID."""
        return encode_tool_call_id(self.tool_call["toolCallId"])


@dataclass
class AvailableCommandsUpdate(AgentMessage):
    """The agent is reporting its slash commands."""

    commands: list[protocol.AvailableCommand]


@dataclass
class CreateTerminal(AgentMessage):
    """Request a terminal in the conversation."""

    terminal_id: str
    command: str
    result_future: Future[bool]
    args: list[str] | None = None
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    output_byte_limit: int | None = None


@dataclass
class KillTerminal(AgentMessage):
    """Kill a terminal process."""

    terminal_id: str


@dataclass
class GetTerminalState(AgentMessage):
    """Get the state of the terminal."""

    terminal_id: str
    result_future: Future[ToolState]


@dataclass
class ReleaseTerminal(AgentMessage):
    """Release the terminal."""

    terminal_id: str


@dataclass
class WaitForTerminalExit(AgentMessage):
    """Wait for the terminal to exit."""

    terminal_id: str
    result_future: Future[tuple[int, str | None]]


@rich.repr.auto
@dataclass
class SetModes(AgentMessage):
    """Set modes from agent."""

    current_mode: str
    modes: dict[str, Mode]


@dataclass
class ModeUpdate(AgentMessage):
    """Agent informed us about a mode change."""

    current_mode: str


@rich.repr.auto
@dataclass
class SetModels(AgentMessage):
    """Set selectable models from an agent's session configuration."""

    current_model: str
    models: dict[str, Model]


@dataclass
class SetThinkingLevels(AgentMessage):
    """Set the current and available model-specific thinking levels."""

    current_level: str
    levels: list[str]


@dataclass
class SessionInfoUpdate(AgentMessage):
    """Agent-provided title for its current session."""

    title: str | None


@dataclass
class CommsUpdated(AgentMessage):
    """The exact shared record plus local attachment context."""

    update: AgentCommsUpdate | QueuePresentation | CursorPresentation
    agent: object | None = None
    session_id: str | None = None
    sequence: int | None = None
    recover_draft: bool = False
    queue_scope: QueueScope | None = None


@dataclass
class UsageUpdage(AgentMessage):
    """Context window change"""

    used: int
    size: int
    cost: tuple[float, str] | None
