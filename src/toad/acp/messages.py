from __future__ import annotations

from asyncio import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING

import rich.repr
from agent_comms.acp_extension import (
    AgentCommsUpdate,
    QueueScope,
)
from textual.message import Message

from acp import schema
from toad.acp.status import ToolCallStatus
from toad.plan import PlanItem
from toad.acp.encode_tool_call_id import encode_tool_call_id

from .attachment_presentation import CursorPresentation, QueuePresentation
from .permission_controller import PermissionRequest

if TYPE_CHECKING:
    from toad.live_output import OutputStream
    from textual.content import Content
    from toad.agent import AgentBase
    from toad.acp.agent_controller import SurfaceBinding
    from toad.acp.terminal_controller import TerminalController
    from toad.terminal_execution import TerminalExecution


class AgentMessage(Message):
    """Base class for agent messages."""


@dataclass
class TerminalProjection(AgentMessage):
    """A queued rendering request retains its original acquisition and binding."""

    binding: SurfaceBinding
    controller: TerminalController
    terminal_id: str
    execution: TerminalExecution


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
    stream: OutputStream
    agent: object


@dataclass
class UserMessage(Message):
    type: str
    text: str


@dataclass
@rich.repr.auto
class RequestPermission(AgentMessage):
    request: PermissionRequest


@dataclass
class Plan(AgentMessage):
    entries: list[PlanItem]


@dataclass
class ToolCall(AgentMessage):
    tool_call: ToolCallStatus

    @property
    def tool_id(self) -> str:
        """An id suitable for use as a TCSS ID."""
        return encode_tool_call_id(self.tool_call.call.tool_call_id)


@dataclass
class ToolCallUpdate(AgentMessage):
    tool_call: ToolCallStatus
    update: schema.ToolCallUpdate

    @property
    def tool_id(self) -> str:
        """An id suitable for use as a TCSS ID."""
        return encode_tool_call_id(self.tool_call.call.tool_call_id)


@dataclass
class AvailableCommandsUpdate(AgentMessage):
    """The agent is reporting its slash commands."""

    commands: list[schema.AvailableCommand]


@dataclass
class ConfigurationChanged(AgentMessage):
    """Invalidate selection presentation; the original agent owns all values."""

    agent: AgentBase


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
