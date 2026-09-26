from __future__ import annotations

from dataclasses import dataclass

from asyncio import Future
from typing import Literal, Mapping, TYPE_CHECKING
from textual.message import Message

import rich.repr
from agent_comms import Goal, GoalExecution, TranscriptCursor, TranscriptEvent, TranscriptPage, MessageRoute

from toad.answer import Answer
from toad.acp import protocol
from toad.acp.encode_tool_call_id import encode_tool_call_id

if TYPE_CHECKING:
    from textual.content import Content
    from toad.acp.agent import Mode, Model
    from toad.widgets.terminal_tool import ToolState


class AgentMessage(Message):
    """Base class for agent messages."""


@dataclass
class GoalSnapshotUpdate(AgentMessage):
    """One paired projection published by the backend goal owner."""

    goal: Goal | None
    execution: GoalExecution | None


class InputDispositionsChanged(AgentMessage):
    """Invalidate the unresolved delivery view; the backend ledger owns its contents."""


class RejectedSessionUpdate(AgentMessage):
    """An invalid ACP notification was logged and excluded from the conversation."""


@dataclass
class McpClientStatus(AgentMessage):
    """Turn-bound package-owned live MCP projection; never a grant or approval."""

    receipt: dict
    turn_id: str
    session_id: str
    agent: object


@dataclass
class McpClientStopped(AgentMessage):
    """The owning connection stopped; its live projection is no longer valid."""

    agent: object


@dataclass
class PromptQueueUpdate(AgentMessage):
    queued: list[str]
    restored: list[str]


@dataclass
class InputStarted(AgentMessage):
    text: str | None


@dataclass
class TranscriptSnapshot(AgentMessage):
    events: tuple[TranscriptEvent, ...]
    page: TranscriptPage | None = None


@dataclass
class TranscriptChanged(AgentMessage):
    cursor: TranscriptCursor | None = None


@dataclass
class CompactionUpdate(AgentMessage):
    """Typed mid-turn lifecycle from agent-comms; not a new user turn."""

    phase: Literal["start", "progress", "end", "abort"]
    reason: str
    summary: str = ""
    will_retry: bool = False
    chunk_index: int = 0
    source_bytes_done: int | None = None
    source_bytes_total: int | None = None
    summary_phase: str | None = None


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
class IncomingMessage(AgentMessage):
    sender: str
    target: str
    text: str
    sequence: int


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
class CoordinationUpdate(AgentMessage):
    """Persistent coordination identity advertised by an ACP agent."""

    thread: str
    wire_root: str
    persistence: str
    transport: str
    worktree: str | None = None
    prompt_queue: bool = False


@dataclass
class TurnStarted(AgentMessage):
    """A server-owned turn began, regardless of who supplied the input."""

    turn_id: str
    started_at: float | None = None
    activity: str | None = None
    activity_detail: str | None = None


@dataclass
class TurnSettled(AgentMessage):
    """The agent finished writing while trailing metadata may still arrive."""

    turn_id: str | None = None


@dataclass
class UsageUpdage(AgentMessage):
    """Context window change"""

    used: int
    size: int
    cost: tuple[float, str] | None
