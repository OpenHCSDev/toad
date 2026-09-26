import asyncio

from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime
import json
import os
from pathlib import Path
from urllib.parse import quote
from typing import Any, cast, NamedTuple
from copy import deepcopy
from math import floor
import rich.repr
from agent_comms import Comms, Goal, GoalExecution, TranscriptCursor, TranscriptPage, MessageRoute
from pydantic import ValidationError

from textual.content import Content
from textual.message import Message
from textual.message_pump import MessagePump


from toad import jsonrpc
import toad
from toad.agent_schema import Agent as AgentData
from toad.agent import AgentBase, AgentReady, AgentFail
from toad.acp import protocol
from toad.acp import api
from toad.acp.api import API
from toad.acp import messages
from toad.acp.sdk_boundary import validate_session_update
from toad.acp.prompt import build as build_prompt
from toad.db import DB
from toad import paths
from toad import constants
from toad.answer import Answer

PROTOCOL_VERSION = 1
PERMISSION_TIMEOUT_SECONDS: float = 120.0


class Mode(NamedTuple):
    """An agent mode."""

    id: str
    name: str
    description: str | None


class Model(NamedTuple):
    """A model selectable for an agent session."""

    id: str
    name: str
    description: str | None


class ContextUsage(NamedTuple):
    """Context window usage."""

    used: int
    size: int
    cost: Cost | None = None

    @property
    def percentage_used(self) -> float:
        try:
            return (self.used / self.size) * 100.0
        except ZeroDivisionError:
            # Sanity check. If size is 0, then 100% is always used?
            return 100.0

    @property
    def percentage_display(self) -> str:
        return f"{floor(self.percentage_used * 10) / 10:.1f}%"


class Cost(NamedTuple):
    """A cost with associated currency."""

    amount: float
    currency: str

    def __str__(self) -> str:
        return f"{self:}"

    def __format__(self, _specifier: str) -> str:
        from format_currency import format_currency

        amount, currency = self
        currency_text = format_currency(amount, currency_code=currency).replace(" ", "")
        return currency_text


class TokenUsage(NamedTuple):
    """Tokens used for a single prompt (per-turn)."""

    total_tokens: int
    input_tokens: int
    output_tokens: int
    thought_tokens: int | None
    cached_read_tokens: int | None
    cached_write_tokens: int | None


def generate_datetime_filename(
    prefix: str, suffix: str, datetime_format: str | None = None
) -> str:
    """Generate a filename which includes the current date and time.

    Useful for ensuring a degree of uniqueness when saving files.

    Args:
        prefix: Prefix to attach to the start of the filename, before the timestamp string.
        suffix: Suffix to attach to the end of the filename, after the timestamp string.
            This should include the file extension.
        datetime_format: The format of the datetime to include in the filename.
            If None, the ISO format will be used.
    """
    if datetime_format is None:
        dt = datetime.now().isoformat()
    else:
        dt = datetime.now().strftime(datetime_format)

    file_name_stem = f"{prefix} {dt}"
    for reserved in ' <>:"/\\|?*.':
        file_name_stem = file_name_stem.replace(reserved, "_")
    return file_name_stem + suffix


@rich.repr.auto
class Agent(AgentBase):
    """An agent that speaks the APC (https://agentclientprotocol.com/overview/introduction) protocol."""

    def __init__(
        self,
        project_root: Path,
        agent: AgentData,
        session_id: str | None,
        session_pk: int | None = None,
    ) -> None:
        """

        Args:
            project_root: Project root path.
            command: Command to launch agent.
        """
        super().__init__(project_root)

        self._agent_data = agent
        self.session_id = session_id

        self.server = jsonrpc.Server()
        self.server.expose_instance(self)

        self._agent_task: asyncio.Task | None = None
        self._task: asyncio.Task | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._process_group_id: int | None = None
        self._stopping = False
        self._reconnecting = False
        self._connected_ok = False
        self.prompt_in_flight = 0
        self._deferred_submissions: set[asyncio.Task] = set()
        self.uses_turn_events = False
        self._pending_session_name: str | None = None
        self._coordination_thread: str | None = None
        self._coordination_root: str | None = None
        self._coordination_worktree: str | None = None
        self._transcript_reader: Comms | None = None
        self._transcript_reader_root: str | None = None
        self._transcript_reader_lock = asyncio.Lock()
        self.server_titles = False
        self.supports_prompt_queue = False
        self._coordination_persistence = "shared on-disk wire"
        self._coordination_transport = "per-session stdio ACP"
        self.session_ready_event = asyncio.Event()
        self.done_event = asyncio.Event()

        self.agent_capabilities: protocol.AgentCapabilities = {
            "loadSession": False,
            "promptCapabilities": {
                "audio": False,
                "embeddedContent": False,
                "image": False,
            },
        }
        self.auth_methods: list[protocol.AuthMethod] = []
        self.session_pk: int | None = session_pk
        self.tool_calls: dict[str, protocol.ToolCall] = {}
        self._message_target: MessagePump | None = None
        self._pending_permission_answers: set[asyncio.Future[Answer | None]] = set()
        self._active_turn_id: str | None = None

        self._terminal_count: int = 0

        log_filename: str = generate_datetime_filename(f"{agent['name']}", ".txt")
        if log_path := os.environ.get("TOAD_LOG"):
            self._log_file_path = Path(log_path).resolve().absolute()
            with suppress(OSError):
                self._log_file_path.unlink(missing_ok=True)
        else:
            self._log_file_path = paths.get_log() / log_filename

        self._token_usage: TokenUsage | None = None
        self._context_usage: ContextUsage | None = None
        self._context_usage_saved = False
        self._model_config_id: str | None = None
        self._thinking_config_id: str | None = None
        self.current_thinking_level: str | None = None
        self.thinking_levels: list[str] = []

    @property
    def command(self) -> str | None:
        """The command used to launch the agent, or `None` if there isn't one."""
        acp_command = toad.get_os_matrix(self._agent_data["run_command"])
        return acp_command

    @property
    def supports_load_session(self) -> bool:
        """Does the agent support loading sessions?"""
        return self.agent_capabilities.get("loadSession", False)

    def __rich_repr__(self) -> rich.repr.Result:
        yield self.project_root_path
        yield self.command

    def log(self, line: str) -> None:
        """Write text to the agent log file.

        Args:
            line: Text to be logged.

        """
        if self._message_target is not None:
            self._message_target.call_later(self._log, line)

    async def _log(self, line: str) -> None:
        """Write text to the agent log file.

        Intended to be called from `log`

        Args:
            line: Text to be logged.
        """

        if self._message_target is None:
            return

        def write_log(log_file_path: Path, line: str):
            """Write log in a thread."""
            try:
                with log_file_path.open("at") as log_file:
                    log_file.write(f"{line.rstrip()}\n")
            except OSError:
                pass

        await asyncio.to_thread(write_log, self._log_file_path, line)

    def get_info(self) -> Content:
        agent_name = self._agent_data["name"]
        return Content(agent_name)

    async def start(self, message_target: MessagePump | None = None) -> None:
        """Start the agent."""
        self._message_target = message_target
        try:
            await asyncio.to_thread(
                self._log_file_path.parent.mkdir, parents=True, exist_ok=True
            )
        except OSError:
            pass
        self._agent_task = asyncio.create_task(self._run_agent())

    def send(self, request: jsonrpc.Request) -> None:
        """Send a request to the agent.

        This is called automatically, if you go through `self.request`.

        Args:
            request: JSONRPC request object.

        """
        if self._process is None:
            self.log("[error] Agent process isnt running")
            return

        self.log(f"[client] {request.body}")
        if (stdin := self._process.stdin) is not None:
            stdin.write(b"%s\n" % request.body_json)

    def request(self) -> jsonrpc.Request:
        """Create a request object."""
        return API.request(self.send)

    def post_message(self, message: Message) -> bool:
        """Post a message to the message target (the Conversation).

        Args:
            message: Message object.

        Returns:
            `True` if the message was posted successfully, or `False` if it wasn't.
        """
        if (message_target := self._message_target) is None:
            return False
        return message_target.post_message(message)

    @jsonrpc.expose("session/update")
    def rpc_session_update(
        self,
        sessionId: str,
        update: Any,
        _meta: dict[str, Any] | None = None,
    ):
        """Agent requests an update.

        https://agentclientprotocol.com/protocol/schema
        """

        try:
            update = validate_session_update(sessionId, update, _meta)
        except ValidationError as error:
            self.log(
                f"[ACP rejected session/update] raw={{'sessionId': {sessionId!r}, "
                f"'update': {update!r}, '_meta': {_meta!r}}}; validation={error}"
            )
            self.post_message(messages.RejectedSessionUpdate())
            return

        metadata = update.get("_meta")
        route: MessageRoute | None = None
        if isinstance(metadata, dict) and isinstance(metadata.get("agentComms"), dict):
            state = metadata["agentComms"]
            mcp_client = state.get("mcpClient")
            if mcp_client is not None:
                receipt = None
                content = update.get("content")
                if (isinstance(content, dict) and content.get("type") == "text"
                        and content.get("text") == ""):
                    receipt = self._mcp_client_receipt(
                        mcp_client, state.get("inputId"), state.get("turnId"),
                        sessionId, update,
                    )
                else:
                    self.log("[ACP MCP live receipt rejected] "
                             f"session={sessionId!r}; chunk is not zero-text")
                if receipt is not None:
                    self.post_message(messages.McpClientStatus(
                        receipt, turn_id=self._active_turn_id,
                        session_id=self.session_id, agent=self,
                    ))
                return
            if isinstance(state.get("thread"), str) and isinstance(state.get("wireRoot"), str):
                self._publish_coordination_metadata({"_meta": metadata})
            if "inputDisposition" in state or state.get("inputDeliveryChanged") is True:
                self.post_message(messages.InputDispositionsChanged())
            failed = state.get("inputFailed")
            if isinstance(failed, dict) and isinstance(failed.get("text"), str):
                self.post_message(
                    messages.InputFailed(
                        failed["text"],
                        failed.get("reason") if isinstance(failed.get("reason"), str) else "Send failed",
                    )
                )
            if "goal" in state or "goalExecution" in state:
                self._publish_goal_snapshot(state)
                self._post_coordination_update()
            compaction = state.get("compaction")
            if isinstance(compaction, dict) and compaction.get("phase") in {"start", "progress", "end", "abort"}:
                if (compaction.get("contextState") == "unknown"
                        and compaction.get("contextUsed") is None):
                    self._context_usage = None
                    self.post_message(messages.UpdateStatusLine(Content("Context estimate unavailable")))
                summary = compaction.get("summary")
                source_done = compaction.get("sourceBytesDone")
                source_total = compaction.get("sourceBytesTotal")
                if not (
                    isinstance(source_done, int) and not isinstance(source_done, bool)
                    and isinstance(source_total, int) and not isinstance(source_total, bool)
                    and 0 <= source_done <= source_total and source_total > 0
                ):
                    source_done = source_total = None
                summary_phase = compaction.get("summaryPhase")
                self.post_message(messages.CompactionUpdate(
                    compaction["phase"],
                    compaction.get("reason") if isinstance(compaction.get("reason"), str)
                    else "unknown",
                    summary if isinstance(summary, str) else "",
                    compaction.get("willRetry") is True,
                    compaction.get("chunkIndex") if isinstance(compaction.get("chunkIndex"), int)
                    and not isinstance(compaction.get("chunkIndex"), bool) else 0,
                    source_done,
                    source_total,
                    summary_phase if isinstance(summary_phase, str) and summary_phase else None,
                ))
                return
            if state.get("transcriptChanged") is True:
                from agent_comms import TranscriptCursor

                checkpoint = state.get("transcriptCursor")
                self.post_message(messages.TranscriptChanged(
                    TranscriptCursor(**checkpoint) if isinstance(checkpoint, dict) else None
                ))
                return
            if isinstance(state.get("route"), dict):
                route = MessageRoute.from_wire(state["route"])
            if isinstance(state.get("queue"), list):
                self.post_message(
                    messages.PromptQueueUpdate(
                        state["queue"], state.get("restored") or []
                    )
                )
                return
            if isinstance(state.get("inputStarted"), dict):
                self.post_message(
                    messages.InputStarted(state["inputStarted"].get("text"))
                )
                return
            if isinstance(state.get("worktree"), str):
                self._coordination_worktree = state["worktree"]
                self.project_root_path = Path(state["worktree"])
                self._post_coordination_update()
            if isinstance(state.get("transcript"), list):
                if not self._reconnecting:
                    from agent_comms import TranscriptEvent, TranscriptPage, TranscriptCursor

                    events = tuple(TranscriptEvent.from_wire(event) for event in state["transcript"])
                    page_data = state.get("transcriptPage")
                    page = TranscriptPage(
                        events, TranscriptCursor(**page_data["before"]),
                        TranscriptCursor(**page_data["after"]),
                        page_data["has_older"], page_data["has_newer"],
                    ) if isinstance(page_data, dict) else None
                    self.post_message(messages.TranscriptSnapshot(events, page))
                return
            turn_id = state.get("turnId")
            if state.get("turnStarted") is True and isinstance(turn_id, str):
                if sessionId != self.session_id or self._stopping:
                    return
                self.uses_turn_events = True
                self._active_turn_id = turn_id
                import math

                started_at = state.get("startedAt")
                if not isinstance(started_at, (int, float)) or not math.isfinite(started_at) or started_at <= 0:
                    started_at = None
                self.post_message(messages.TurnStarted(
                    turn_id, started_at,
                    state.get("activity") if isinstance(state.get("activity"), str) else None,
                    state.get("activityDetail") if isinstance(state.get("activityDetail"), str) else None,
                ))
                return
            if state.get("turnSettled") is True:
                if sessionId != self.session_id or self._stopping:
                    return
                if isinstance(turn_id, str):
                    self.uses_turn_events = True
                # Only the current session's own matching settled turn may
                # retire the receipt gate; a stale queued settlement from an
                # older turn must not clear the current one.
                if sessionId == self.session_id and turn_id == self._active_turn_id:
                    self._active_turn_id = None
                self.post_message(messages.TurnSettled(turn_id))
                return
            incoming = metadata["agentComms"].get("incoming")
            if isinstance(incoming, dict):
                self.post_message(
                    messages.IncomingMessage(
                        sender=str(incoming["sender"]),
                        target=str(incoming["target"]),
                        text=str(incoming["body"]),
                        sequence=int(incoming["sequence"]),
                    )
                )
                return
        match update:
            case {
                "sessionUpdate": "user_message_chunk",
                "content": {"type": type, "text": text},
            }:
                if text:
                    self.post_message(messages.UserMessage(type, text))

            case {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": type, "text": text},
            }:
                if text:
                    if type == "text" and text.startswith("[agent error]"):
                        text += f"\n\n[Open ACP log]({quote(str(self._log_file_path))})"
                    self.post_message(messages.Update(type, text, route))

            case {
                "sessionUpdate": "agent_thought_chunk",
                "content": {"type": type, "text": text},
            }:
                self.post_message(messages.Thinking(type, text))

            case {
                "sessionUpdate": "tool_call",
                "toolCallId": tool_call_id,
            }:
                self.tool_calls[tool_call_id] = update
                self.post_message(messages.ToolCall(update))

            case {"sessionUpdate": "plan", "entries": entries}:
                self.post_message(messages.Plan(entries))

            case {
                "sessionUpdate": "tool_call_update",
                "toolCallId": tool_call_id,
            }:
                if tool_call_id in self.tool_calls:
                    current_tool_call = self.tool_calls[tool_call_id]
                    for key, value in update.items():
                        if value is not None:
                            current_tool_call[key] = value

                    self.post_message(
                        messages.ToolCallUpdate(deepcopy(current_tool_call), update)
                    )
                else:
                    # The agent can send a tool call update, without previously sending the tool call *rolls eyes*
                    current_tool_call: protocol.ToolCall = {
                        "sessionUpdate": "tool_call",
                        "toolCallId": tool_call_id,
                        "title": "Tool call",
                    }
                    for key, value in update.items():
                        if value is not None:
                            current_tool_call[key] = value

                    self.tool_calls[tool_call_id] = current_tool_call
                    self.post_message(messages.ToolCall(current_tool_call))

            case {
                "sessionUpdate": "available_commands_update",
                "availableCommands": available_commands,
            }:
                self.post_message(messages.AvailableCommandsUpdate(available_commands))

            case {"sessionUpdate": "current_mode_update", "currentModeId": mode_id}:
                self.post_message(messages.ModeUpdate(mode_id))

            case {
                "sessionUpdate": "config_option_update",
                "configOptions": config_options,
            }:
                self._publish_models({"configOptions": config_options})

            case {"sessionUpdate": "session_info_update"} if "title" in update:
                title = update.get("title")
                if self._coordination_root is not None and isinstance(title, str):
                    identity = (
                        (update.get("_meta") or {})
                        .get("agentComms", {})
                        .get("thread", title)
                    )
                    self._coordination_thread = identity
                    self._post_coordination_update()
                    self.post_message(messages.SessionInfoUpdate(title))
                else:
                    self.post_message(messages.SessionInfoUpdate(title))

            case {"sessionUpdate": "usage_update", "used": used, "size": size}:
                self._context_usage_saved = False
                # Pi can report zero immediately after compaction or while a
                # turn has not yet returned authoritative usage. A saved
                # conversation still has context; presenting 0.0K (0.0%)
                # falsely implies it is empty. Do not reuse a pre-compaction
                # number either: wait for a new positive measurement.
                if used <= 0 or size <= 0:
                    self._context_usage = None
                    self.post_message(messages.UpdateStatusLine(Content("Context estimate unavailable")))
                    return
                match update.get("cost"):
                    case {"amount": amount, "currency": currency}:
                        self._context_usage = ContextUsage(
                            used, size, Cost(amount, currency)
                        )
                    case _:
                        self._context_usage = ContextUsage(used, size)
                self.update_status_line()

    _MCP_SERVER_STATES = frozenset({
        "ready", "error", "disabled", "trust_required", "unsupported_env",
        "denied", "stale_restart_required", "connecting", "approved",
    })

    def _mcp_client_receipt(
        self, value: object, meta_input_id: object, envelope_turn_id: object,
        session_id: str, update: object,
    ) -> dict | None:
        """Accept only an exact, session/turn-bound version-1 live receipt.

        The DTO is redacted and never an approval. Stale receipts from a
        previous turn or another session are rejected, never rendered; the
        envelope must carry the same server-owned ACP turn this agent is
        currently inside. Malformed data is logged as a reason only, without
        echoing untrusted receipt content.
        """
        import re

        def fail(reason: str) -> None:
            self.log(f"[ACP MCP live receipt rejected] session={session_id!r}; {reason}")

        if not isinstance(value, dict):
            fail("receipt not an object")
            return None
        if type(value.get("version")) is not int or value["version"] != 1:
            fail("unsupported receipt version")
            return None
        if session_id != self.session_id:
            fail("receipt does not belong to this session")
            return None
        if (value.get("source") != "pi-mcp-client"
                or not isinstance(value.get("inputId"), str)
                or not re.fullmatch(r"[a-f0-9]{32}", value["inputId"])
                or value.get("state") != "running" or value.get("lifetime") != "turn"):
            fail("unsupported receipt identity")
            return None
        if isinstance(meta_input_id, str) and meta_input_id != value["inputId"]:
            fail("receipt inputId does not match envelope")
            return None
        # The envelope must bind this exact active ACP turn. This excludes
        # stale queued events and old receipts replayed into a later turn;
        # relays without turn identity fail closed here.
        if (not isinstance(envelope_turn_id, str) or self._active_turn_id is None
                or envelope_turn_id != self._active_turn_id):
            fail("receipt is not bound to the active ACP turn")
            return None
        servers = value.get("servers")
        if not isinstance(servers, list) or len(servers) > 32:
            fail("invalid server rows")
            return None
        seen: set[str] = set()
        for row in servers:
            if (not isinstance(row, dict)
                    or not isinstance(row.get("id"), str)
                    or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", row["id"])
                    or row["id"] in seen
                    or row.get("scope") not in ("user", "project")
                    or row.get("state") not in self._MCP_SERVER_STATES
                    or row.get("calls") not in ("automatic", "confirm", "unavailable")):
                fail("invalid or duplicate server row")
                return None
            seen.add(row["id"])
            counts = [row.get(name) for name in ("tools", "resources", "prompts")]
            if (any(type(count) is not int or not 0 <= count <= 10_000 for count in counts)
                    or (row["state"] == "ready") == (row["calls"] == "unavailable")
                    or (row["state"] != "ready" and any(counts))):
                fail("inconsistent server row")
                return None
        return value

    def update_status_line(self) -> None:
        """Update the current status line."""

        if (usage := self._context_usage) is not None:
            status: list[Content] = []
            status.append(
                Content.assemble(
                    f"{usage.used / 1000:.1f}K",
                    " (",
                    (f"{usage.percentage_display}", "bold"),
                    ")",
                )
            )
            if self._context_usage_saved:
                status.append(Content("last response"))
            if (cost := usage.cost) is not None:
                status.append(Content.assemble((f"{cost}", "bold")))

            status_line = Content(" • ").join(status)
            self.post_message(messages.UpdateStatusLine(status_line))

    @jsonrpc.expose("session/request_permission")
    async def rpc_request_permission(
        self,
        sessionId: str,
        options: list[protocol.PermissionOption],
        toolCall: protocol.ToolCallUpdatePermissionRequest,
        _meta: dict | None = None,
    ) -> protocol.RequestPermissionResponse:
        """Agent requests permission to make a tool call.

        Args:
            sessionId: The session ID.
            options: A list of permission options (potential replies).
            toolCall: The tool or tools the agent is requesting permission to call.
            _meta: Optional meta information.

        Returns:
            The response to the permission request.
        """
        cancelled: protocol.RequestPermissionResponse = {"outcome": {"outcome": "cancelled"}}
        if self._stopping or sessionId != self.session_id:
            return cancelled
        result_future: asyncio.Future[Answer | None] = asyncio.get_running_loop().create_future()
        tool_call_id = toolCall["toolCallId"]

        permission_tool_call = cast(dict[str, Any], toolCall.copy())
        permission_tool_call.pop("sessionUpdate", None)
        visible_tool_call: dict[str, Any] = (
            deepcopy(dict(self.tool_calls[tool_call_id])) if tool_call_id in self.tool_calls else {}
        )
        visible_tool_call.update(permission_tool_call)
        message = messages.RequestPermission(
            options, cast(protocol.ToolCallUpdatePermissionRequest, visible_tool_call), result_future
        )
        if not self.post_message(message):
            return cancelled  # No mounted controller can answer this request.
        self.tool_calls[tool_call_id] = cast(protocol.ToolCall, deepcopy(visible_tool_call))
        self._pending_permission_answers.add(result_future)
        try:
            try:
                ask_result = await asyncio.wait_for(result_future, PERMISSION_TIMEOUT_SECONDS)
            except TimeoutError:
                return cancelled
        finally:
            self._pending_permission_answers.discard(result_future)
        if ask_result is None or self._stopping or sessionId != self.session_id:
            return cancelled
        if not any(option["optionId"] == ask_result.id for option in options):
            return cancelled
        return {"outcome": {"optionId": ask_result.id, "outcome": "selected"}}

    @jsonrpc.expose("fs/read_text_file")
    def rpc_read_text_file(
        self,
        sessionId: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
    ) -> dict[str, str]:
        """Read a file in the project."""
        # TODO: what if the read is outside of the project path?
        # https://agentclientprotocol.com/protocol/file-system#reading-files
        read_path = self.project_root_path / path
        try:
            text = read_path.read_text(encoding="utf-8", errors="ignore")
        except IOError:
            text = ""
        if line is not None:
            line = max(0, line - 1)
            if limit is None:
                text = "\n".join(text.splitlines()[line:])
            else:
                text = "\n".join(text.splitlines()[line : line + limit])
        return {"content": text}

    @jsonrpc.expose("fs/write_text_file")
    def rpc_write_text_file(self, sessionId: str, path: str, content: str) -> None:
        # TODO: What if the agent wants to write outside of the project path?
        # https://agentclientprotocol.com/protocol/file-system#writing-files

        write_path = self.project_root_path / path
        write_path.write_text(content, encoding="utf-8", errors="ignore")

    # https://agentclientprotocol.com/protocol/schema#createterminalrequest
    @jsonrpc.expose("terminal/create")
    async def rpc_terminal_create(
        self,
        command: str,
        _meta: dict | None = None,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: list[protocol.EnvVariable] | None = None,
        outputByteLimit: int | None = None,
        sessionId: str | None = None,
    ) -> protocol.CreateTerminalResponse:
        # Assign a terminal id
        self._terminal_count = self._terminal_count + 1
        terminal_id = f"terminal-{self._terminal_count}"

        terminal_env = (
            {variable["name"]: variable["value"] for variable in env} if env else {}
        )
        result_future: asyncio.Future[bool] = asyncio.Future()
        self.post_message(
            messages.CreateTerminal(
                terminal_id,
                command=command,
                args=args,
                cwd=cwd,
                env=terminal_env,
                output_byte_limit=outputByteLimit,
                result_future=result_future,
            )
        )
        await result_future
        if not result_future.result():
            raise jsonrpc.JSONRPCError("Failed to create a terminal.")
        return {"terminalId": terminal_id}

    # https://agentclientprotocol.com/protocol/schema#killterminalcommandrequest
    @jsonrpc.expose("terminal/kill")
    def rpc_terminal_kill(
        self, sessionID: str, terminalId: str, _meta: dict | None = None
    ) -> protocol.KillTerminalCommandResponse:
        self.post_message(messages.KillTerminal(terminalId))
        return {}

    # https://agentclientprotocol.com/protocol/schema#terminal%2Foutput
    @jsonrpc.expose("terminal/output")
    async def rpc_terminal_output(
        self, sessionId: str, terminalId: str, _meta: dict | None = None
    ) -> protocol.TerminalOutputResponse:
        from toad.widgets.terminal_tool import ToolState

        result_future: asyncio.Future[ToolState] = asyncio.Future()

        if not self.post_message(messages.GetTerminalState(terminalId, result_future)):
            raise RuntimeError("Unable to get terminal output")

        await result_future
        terminal_state = result_future.result()

        result: protocol.TerminalOutputResponse = {
            "output": terminal_state.output,
            "truncated": terminal_state.truncated,
        }
        if (return_code := terminal_state.return_code) is not None:
            result["exitStatus"] = {"exitCode": return_code}
        return result

    # https://agentclientprotocol.com/protocol/schema#terminal%2Frelease
    @jsonrpc.expose("terminal/release")
    def rpc_terminal_release(
        self, sessionId: str, terminalId: str, _meta: dict | None = None
    ) -> protocol.ReleaseTerminalResponse:
        self.post_message(messages.ReleaseTerminal(terminalId))
        return {}

    # https://agentclientprotocol.com/protocol/schema#terminal%2Fwait-for-exit
    @jsonrpc.expose("terminal/wait_for_exit")
    async def rpc_terminal_wait_for_exit(
        self, sessionId: str, terminalId: str, _meta: dict | None = None
    ) -> protocol.WaitForTerminalExitResponse:
        result_future: asyncio.Future[tuple[int, str | None]] = asyncio.Future()
        if not self.post_message(
            messages.WaitForTerminalExit(terminalId, result_future)
        ):
            raise RuntimeError("Unable to wait for terminal exit; no terminal found")

        await result_future
        return_code, signal = result_future.result()
        return {"exitCode": return_code, "signal": signal}

    async def _run_agent(self) -> None:
        """Task to communicate with the agent subprocess."""

        PIPE = asyncio.subprocess.PIPE
        env = os.environ.copy()
        env["TOAD_CWD"] = str(Path("./").absolute())

        if (command := self.command) is None:
            self.post_message(
                AgentFail("Failed to start agent; no run command for this OS")
            )
            return
        try:
            process = self._process = await asyncio.create_subprocess_shell(
                command,
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
                env=env,
                cwd=str(self.project_root_path),
                limit=10 * 1024 * 1024,
                start_new_session=os.name != "nt",
            )
            if os.name != "nt":
                self._process_group_id = process.pid
        except Exception as error:
            self.post_message(AgentFail("Failed to start agent", details=str(error)))
            return

        self._task = asyncio.create_task(self.run())

        assert process.stdout is not None
        assert process.stdin is not None

        tasks: set[asyncio.Task] = set()

        async def call_jsonrpc(request: jsonrpc.JSONObject | jsonrpc.JSONList) -> None:
            try:
                if (result := await self.server.call(request)) is not None:
                    result_json = json.dumps(result).encode("utf-8")
                    if process.stdin is not None:
                        process.stdin.write(b"%s\n" % result_json)
            finally:
                if (task := asyncio.current_task()) is not None:
                    tasks.discard(task)

        while line := await process.stdout.readline():
            # This line should contain JSON, which may be:
            #   A) a JSONRPC request
            #   B) a JSONRPC response to a previous request
            if not line.strip():
                continue

            try:
                line_str = line.decode("utf-8")
            except Exception as error:
                self.log(f"[error] Unable to decode utf-8 from agent: {error}")
                continue

            self.log(f"[agent] {line_str}")
            try:
                agent_data: jsonrpc.JSONType = json.loads(line_str)
            except Exception as error:
                self.log(f"[error] failed to decode JSON from agent: {error}")
                continue

            if isinstance(agent_data, dict):
                if "result" in agent_data or "error" in agent_data:
                    API.process_response(agent_data)
                    continue

            elif isinstance(agent_data, list):
                if not all(isinstance(datum, dict) for datum in agent_data):
                    self.log(f"[error] Agent sent invalid data: {agent_data!r}")
                    continue
                if all(
                    isinstance(datum, dict) and ("result" in datum or "error" in datum)
                    for datum in agent_data
                ):
                    API.process_response(agent_data)
                    continue

            if not isinstance(agent_data, dict):
                self.log("[error] Invalid JSON from agent {agent_data!r}")
                continue

            # By this point we know it is a JSON RPC call
            assert isinstance(agent_data, dict)
            tasks.add(asyncio.create_task(call_jsonrpc(agent_data)))
            await asyncio.sleep(0)

        # Cancel all remaining tasks and wait for them to finish
        for task in tasks:
            task.cancel()

        # Wait for all tasks to complete cancellation
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if process.returncode and not self._stopping:
            assert process.stderr is not None
            fail_details = (await process.stderr.read()).decode("utf-8", "replace")
            self.post_message(
                AgentFail(
                    f"Agent returned a failure code: [b]{process.returncode}",
                    details=fail_details,
                )
            )

        if (
            not self._stopping
            and self._process_group_id is not None
            and self._process_group_alive(self._process_group_id)
        ):
            with suppress(OSError):
                os.killpg(self._process_group_id, 15)
            await asyncio.sleep(0.1)
            if self._process_group_alive(self._process_group_id):
                with suppress(OSError):
                    os.killpg(self._process_group_id, 9)
        self._process_group_id = None
        self._process = None

    async def stop(self) -> None:
        """Gracefully stop the process."""
        self._stopping = True
        self._active_turn_id = None
        self.post_message(messages.McpClientStopped(self))
        for answer in tuple(self._pending_permission_answers):
            if not answer.done():
                answer.set_result(None)
        if self.session_pk is not None:
            db = DB()
            await db.session_update_last_used(self.session_pk)

        process = self._process
        process_group = self._process_group_id
        if (
            process is not None
            and process.returncode is None
            and process.stdin is not None
        ):
            process.stdin.close()
            with suppress(BrokenPipeError, ConnectionResetError):
                await process.stdin.wait_closed()
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=1)
        if os.name != "nt" and process_group is not None:
            with suppress(OSError):
                os.killpg(process_group, 15)
            if process is not None and process.returncode is None:
                with suppress(TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=3)
            if self._process_group_alive(process_group):
                with suppress(OSError):
                    os.killpg(process_group, 9)
                deadline = asyncio.get_running_loop().time() + 1
                while (
                    self._process_group_alive(process_group)
                    and asyncio.get_running_loop().time() < deadline
                ):
                    await asyncio.sleep(0.05)
            if process is not None and process.returncode is None:
                with suppress(TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=1)
        elif process is not None and process.returncode is None:
            try:
                process.terminate()
            except OSError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                try:
                    process.kill()
                except OSError:
                    pass
                with suppress(TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=1)

        current = asyncio.current_task()
        for task in (self._task, self._agent_task):
            if task is not None and task is not current and not task.done():
                task.cancel()
        pending = [
            task
            for task in (self._task, self._agent_task)
            if task is not None and task is not current
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._process_group_id = None
        self._process = None

    @staticmethod
    def _process_group_alive(process_group: int) -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    async def run(self) -> None:
        """The main logic of the Agent."""
        if constants.ACP_INITIALIZE:
            self._connected_ok = False
            try:
                # Boilerplate to initialize comms
                await self.acp_initialize()

                if self.session_id is None:
                    # Create a new session
                    await self.acp_new_session()
                else:
                    # Load existing session
                    if not self.agent_capabilities.get("loadSession", False):
                        self.post_message(
                            AgentFail(
                                "Resume not supported",
                                f"{self._agent_data['name']} does not currently support resuming sessions.",
                                help="no_resume",
                            )
                        )
                        self.session_ready_event.set()
                        return
                    await self.acp_load_session()
                    if self.session_pk is not None:
                        db = DB()
                        await db.session_update_last_used(self.session_pk)
                self._connected_ok = True
            except jsonrpc.APIError as error:
                if isinstance(error.data, dict):
                    reason = str(
                        error.data.get("reason") or "Failed to initialize agent"
                    )
                    details = str(
                        error.data.get("details") or error.data.get("error") or ""
                    )
                else:
                    reason = "Failed to initialize agent"
                    details = ""
                self.post_message(AgentFail(reason, details))

        self.session_ready_event.set()
        self.post_message(AgentReady(reconnected=self._reconnecting))

    async def send_prompt(
        self, prompt: str, *, delivery: str = "queue", defer_display: bool = False
    ) -> str | None:
        """Send a prompt to the agent.

        !!! note
            This method blocks as it may defer to a thread to read resources.

        Args:
            prompt: Prompt text.
        """
        self.prompt_in_flight += 1
        submission = asyncio.current_task() if defer_display else None
        if submission is not None:
            self._deferred_submissions.add(submission)
        try:
            prompt_content_blocks = await asyncio.to_thread(
                build_prompt, self.project_root_path, prompt
            )
            if any(block.get("type") == "image" for block in prompt_content_blocks):
                supported = (
                    getattr(self, "supports_prompt_images", False)
                    if self._coordination_root is not None
                    else (self.agent_capabilities.get("promptCapabilities") or {}).get("image", False)
                )
                if not supported:
                    raise ValueError("This agent owner does not support images yet; refresh it while idle.")
            return await self.acp_session_prompt(
                prompt_content_blocks,
                {
                    "agentComms": {
                        "delivery": delivery,
                        "deferDisplay": defer_display,
                        "userText": prompt,
                    }
                },
            )
        finally:
            self.prompt_in_flight -= 1
            if submission is not None:
                self._deferred_submissions.discard(submission)

    async def clear_queue(self) -> None:
        """Drop prompts still awaiting delivery, leaving the turn running."""
        await self.acp_session_prompt(
            [{"type": "text", "text": " "}], {"agentComms": {"clearQueue": True}}
        )

    async def send_now(self) -> bool:
        """Interrupt the response for already queued input, without resending text."""
        # Resource/image preparation can still be running when the user clicks.
        # Wait for those exact submissions to reach the owner before interrupting.
        if pending := tuple(self._deferred_submissions):
            await asyncio.gather(*(asyncio.shield(task) for task in pending))
        result = await self.acp_session_prompt(
            [{"type": "text", "text": " "}], {"agentComms": {"sendNow": True}}
        )
        return result is not None

    async def compact_context(self, instructions: str | None = None) -> dict[str, Any]:
        """Ask the persistent owner to compact Pi context without creating a turn."""
        metadata = {"agentComms": {"compact": instructions}}
        with self.request():
            request = api.session_prompt(
                [{"type": "text", "text": " "}], self.session_id, metadata
            )
        try:
            response = await request.wait()
        except (jsonrpc.APIError, jsonrpc.JSONRPCError) as error:
            return {"ok": False, "error": error.message or "Compaction request failed"}
        if not isinstance(response, dict):
            return {"ok": False, "error": "Compaction returned no result"}
        result = (response.get("_meta") or {}).get("agentComms", {}).get("compaction")
        return result if isinstance(result, dict) else {
            "ok": False,
            "error": "Compaction result was missing",
        }

    async def reconnect_after_auth(self) -> None:
        await self.reconnect()

    async def reconnect(self) -> None:
        """Reattach the existing view after login or an explicit owner start."""
        if self.session_id is not None and not self.supports_load_session:
            raise ValueError(
                "This agent cannot resume its session."
            )
        target = self._message_target
        await self.stop()
        self._stopping = False
        self._reconnecting = True
        self.session_ready_event.clear()
        try:
            await self.start(target)
            await asyncio.wait_for(self.session_ready_event.wait(), timeout=30)
            if not self._connected_ok:
                raise ValueError("The agent could not reconnect.")
        finally:
            self._reconnecting = False

    async def authenticate(self, method_id: str) -> None:
        with self.request():
            response = api.authenticate(method_id)
        await response.wait()
        await self.acp_initialize()

    async def acp_initialize(self):
        """Initialize agent."""
        with self.request():
            initialize_response = api.initialize(
                PROTOCOL_VERSION,
                {
                    "fs": {
                        "readTextFile": True,
                        "writeTextFile": True,
                    },
                    "terminal": True,
                    "auth": {"terminal": os.name != "nt"},
                    "_meta": {"agentComms": {"transcriptSnapshots": True, "transcriptDiffs": True}},
                },
                {
                    "name": toad.NAME,
                    "title": toad.TITLE,
                    "version": toad.get_version(),
                },
            )

        response = await initialize_response.wait()
        assert response is not None

        # Store agents capabilities
        if agent_capabilities := response.get("agentCapabilities"):
            self.agent_capabilities = agent_capabilities
        self.auth_methods = response.get("authMethods") or []

    async def acp_new_session(self) -> None:
        """Create a new session."""
        with self.request():
            session_new_response = api.session_new(
                str(self.project_root_path),
                [],
            )
        response = await session_new_response.wait()
        assert response is not None
        self.session_id = response["sessionId"]

        if self.supports_load_session:
            db = DB()
            session_name = (self._pending_session_name if self._pending_session_name is not None
                            else self._initial_session_title(response) or "New Session")
            self.session_pk = await db.session_new(
                session_name,
                self._agent_data["name"],
                self._agent_data["identity"],
                self.session_id,
                protocol="acp",
                meta={
                    "cwd": str(self.project_root_path),
                    "agent_data": self._agent_data,
                },
            )
            if self.session_pk is not None and self._pending_session_name is not None:
                await db.session_update_title(
                    self.session_pk, self._pending_session_name
                )

        if (modes := response.get("modes", None)) is not None:
            current_mode = modes["currentModeId"]
            available_modes = modes["availableModes"]
            modes_update = {
                mode["id"]: Mode(
                    mode["id"], mode["name"], mode.get("description", None)
                )
                for mode in available_modes
            }
            self.post_message(messages.SetModes(current_mode, modes_update))
        self._publish_models(response)
        self._publish_coordination_metadata(response, initial=True)

    async def acp_load_session(self) -> None:
        assert self.session_id is not None, "Session id must be set"
        cwd = str(self.project_root_path)
        if self.session_pk is not None:
            db = DB()
            if (session := await db.session_get(self.session_pk)) is not None:
                if session["meta_json"]:
                    meta = json.loads(session["meta_json"])
                    if session_cwd := meta.get("cwd", None):
                        cwd = session_cwd
                    if agent_data := meta.get("agent_data"):
                        self._agent_data = agent_data

        with self.request():
            session_load_response = api.session_load(cwd, [], self.session_id)
        response = await session_load_response.wait()
        assert response is not None

        if (modes := response.get("modes", None)) is not None:
            current_mode = modes["currentModeId"]
            available_modes = modes["availableModes"]
            modes_update = {
                mode["id"]: Mode(
                    mode["id"], mode["name"], mode.get("description", None)
                )
                for mode in available_modes
            }
            self.post_message(messages.SetModes(current_mode, modes_update))
        self._publish_models(response)
        self._publish_coordination_metadata(response, initial=True)

    def _publish_models(self, response: Mapping[str, object]) -> None:
        """Publish model and thinking-level config options, with legacy fallback."""
        config_options = response.get("configOptions")
        if isinstance(config_options, list):
            self._model_config_id = None
            self._thinking_config_id = None
            for config in config_options:
                if not isinstance(config, dict) or config.get("type") != "select":
                    continue
                current = config.get("currentValue")
                raw_options = config.get("options")
                if not isinstance(current, str) or not isinstance(raw_options, list):
                    continue
                options: list[Mapping[str, object]] = []
                for option in raw_options:
                    if not isinstance(option, dict):
                        continue
                    grouped = option.get("options")
                    if isinstance(grouped, list):
                        options.extend(
                            item for item in grouped if isinstance(item, dict)
                        )
                    else:
                        options.append(option)
                if config.get("category") == "model" or config.get("id") == "model":
                    models = {
                        str(option["value"]): Model(
                            str(option["value"]),
                            str(option.get("name") or option["value"]),
                            (
                                str(option["description"])
                                if option.get("description") is not None
                                else None
                            ),
                        )
                        for option in options
                        if isinstance(option.get("value"), str)
                    }
                    if current not in models:
                        continue
                    self._model_config_id = str(config["id"])
                    self.post_message(messages.SetModels(current, models))
                elif config.get("id") == "thinking_level":
                    levels = [
                        str(option["value"])
                        for option in options
                        if isinstance(option.get("value"), str)
                    ]
                    if current in levels:
                        self._thinking_config_id = str(config["id"])
                        self.current_thinking_level = current
                        self.thinking_levels = levels
                        self.post_message(messages.SetThinkingLevels(current, levels))
            if self._model_config_id is None:
                self.post_message(messages.SetModels("", {}))
            return

        legacy_models = response.get("models")
        if not isinstance(legacy_models, dict):
            return
        current = legacy_models.get("currentModelId")
        available = legacy_models.get("availableModels")
        if not isinstance(current, str) or not isinstance(available, list):
            return
        models = {
            str(model["modelId"]): Model(
                str(model["modelId"]),
                str(model.get("name") or model["modelId"]),
                (
                    str(model["description"])
                    if model.get("description") is not None
                    else None
                ),
            )
            for model in available
            if isinstance(model, dict) and isinstance(model.get("modelId"), str)
        }
        if current in models:
            self.post_message(messages.SetModels(current, models))

    @staticmethod
    def _initial_session_title(response: Mapping[str, object]) -> str | None:
        """Opening metadata owns the display title, with canonical identity as fallback."""
        metadata = response.get("_meta")
        if not isinstance(metadata, dict):
            return None
        coordination = metadata.get("agentComms")
        if (not isinstance(coordination, dict)
                or not isinstance(coordination.get("thread"), str)
                or not isinstance(coordination.get("wireRoot"), str)):
            return None
        for field in ("title", "thread"):
            value = coordination.get(field)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _publish_goal_snapshot(self, state: Mapping[str, object]) -> None:
        if "goal" not in state or "goalExecution" not in state:
            return
        try:
            raw_goal, raw_execution = state["goal"], state["goalExecution"]
            goal = Goal(**raw_goal) if isinstance(raw_goal, dict) else None
            execution = GoalExecution.from_wire(raw_execution) if isinstance(raw_execution, dict) else None
            if raw_goal is not None and goal is None or raw_execution is not None and execution is None:
                raise ValueError("Invalid goal snapshot")
            if execution is not None and (goal is None or execution.goal_id != goal.id):
                raise ValueError("Goal execution identity does not match goal snapshot")
        except (KeyError, TypeError, ValueError) as error:
            self.log(f"[ACP rejected goal snapshot] {error}")
            return
        self.post_message(messages.GoalSnapshotUpdate(goal, execution))

    def _publish_coordination_metadata(
        self, response: Mapping[str, object], *, initial: bool = False,
    ) -> None:
        metadata = response.get("_meta")
        if not isinstance(metadata, dict):
            return
        coordination = metadata.get("agentComms")
        if not isinstance(coordination, dict):
            return
        if initial:
            self._publish_goal_snapshot(coordination)
            self.post_message(messages.InputDispositionsChanged())
        thread = coordination.get("thread")
        wire_root = coordination.get("wireRoot")
        if not isinstance(thread, str) or not isinstance(wire_root, str):
            return
        if "contextUsage" in coordination:
            saved = coordination["contextUsage"]
            if (
                isinstance(saved, dict)
                and isinstance(saved.get("used"), int) and saved["used"] > 0
                and isinstance(saved.get("size"), int) and saved["size"] > 0
            ):
                self._context_usage = ContextUsage(saved["used"], saved["size"])
                self._context_usage_saved = True
                self.update_status_line()
            else:
                self._context_usage = None
                self._context_usage_saved = False
                self.post_message(messages.UpdateStatusLine(Content("Context estimate unavailable")))
        self._coordination_thread = thread
        self._coordination_root = wire_root
        if isinstance(worktree := coordination.get("worktree"), str):
            self._coordination_worktree = worktree
            self.project_root_path = Path(worktree)
        self.uses_turn_events = coordination.get("turnLifecycle") is True
        self.server_titles = coordination.get("autoTitle") is True
        self.supports_prompt_queue = coordination.get("promptQueue") is True
        self.supports_prompt_images = coordination.get("imagePrompts") is True
        pending_name = self._pending_session_name
        title = (pending_name if pending_name is not None else
                 self._initial_session_title(response) if initial else coordination.get("title"))
        if isinstance(title, str):
            self.post_message(messages.SessionInfoUpdate(title))
        self._coordination_owner_pid = coordination.get("ownerPid")
        self._coordination_persistence = str(
            coordination.get("persistence", "shared on-disk wire")
        )
        self._coordination_transport = str(
            coordination.get("transport", "per-session stdio ACP")
        )
        if pending_name:
            self._rename_coordination_thread(pending_name)
            self._pending_session_name = None
        else:
            self._post_coordination_update()

    def _post_coordination_update(self) -> None:
        thread = self._coordination_thread
        wire_root = self._coordination_root
        if thread is None or wire_root is None:
            return
        self.post_message(
            messages.CoordinationUpdate(
                thread=thread,
                wire_root=wire_root,
                persistence=self._coordination_persistence,
                transport=self._coordination_transport,
                worktree=getattr(self, "_coordination_worktree", None),
                prompt_queue=getattr(self, "supports_prompt_queue", False),
            )
        )

    def _rename_coordination_thread(self, display_name: str) -> None:
        thread = self._coordination_thread
        wire_root = self._coordination_root
        process = self._process
        if thread is None or wire_root is None or process is None:
            return

        from agent_comms.operations import wire

        result = wire(wire_root).rename_managed_thread(
            thread,
            display_name,
            owner_pid=getattr(self, "_coordination_owner_pid", None) or process.pid,
        )
        self._coordination_thread = result.current
        self._post_coordination_update()

    async def acp_session_prompt(
        self, prompt: list[protocol.ContentBlock], metadata: dict | None = None
    ) -> str | None:
        """Send the prompt to the agent.

        Returns:
            The stop reason.

        """
        with self.request():
            session_prompt = api.session_prompt(prompt, self.session_id, metadata or {})
        try:
            result = await session_prompt.wait()
        except jsonrpc.APIError as error:
            data = error.data if isinstance(error.data, dict) else {}
            details = next(
                (
                    value
                    for key in ("details", "reason", "error")
                    if isinstance((value := data.get(key)), str) and value.strip()
                ),
                error.message or f"{self._agent_data['name']} returned an error",
            )

            user_text = (metadata or {}).get("agentComms", {}).get("userText")
            if isinstance(user_text, str) and user_text:
                self.post_message(messages.InputFailed(user_text, details))

            self.post_message(
                AgentFail(
                    "Failed to send prompt",
                    details,
                    help="prompt",
                )
            )
            return None
        except jsonrpc.JSONRPCError as error:
            user_text = (metadata or {}).get("agentComms", {}).get("userText")
            if isinstance(user_text, str) and user_text:
                self.post_message(messages.InputFailed(user_text, error.message or "Connection failed"))
            self.post_message(
                AgentFail(
                    "Failed to send prompt",
                    (error.message or f"{self._agent_data['name']} returned an error"),
                    help="prompt",
                )
            )
            return None

        assert result is not None
        return result.get("stopReason")

    async def acp_session_set_mode(self, mode_id: str) -> str | None:
        """Update the current mode with the agent."""
        with self.request():
            response = api.session_set_mode(self.session_id, mode_id)
        try:
            await response.wait()
        except jsonrpc.APIError as error:
            match error.data:
                case {"details": details}:
                    return details if isinstance(details, str) else "Failed to set mode"
            return "Failed to set mode"
        else:
            return None

    async def set_mode(self, mode_id: str) -> str | None:
        return await self.acp_session_set_mode(mode_id)

    async def set_model(self, model_id: str) -> str | None:
        """Update the session model through ACP config options."""
        if self._model_config_id is None:
            return "This agent does not advertise model configuration"
        with self.request():
            response = api.session_set_config_option(
                self.session_id, self._model_config_id, model_id
            )
        try:
            result = await response.wait()
        except (jsonrpc.APIError, jsonrpc.JSONRPCError) as error:
            if isinstance(getattr(error, "data", None), dict):
                details = error.data.get("details") or error.data.get("reason")
                if isinstance(details, str):
                    return details
            return "Failed to set model"
        if result is not None:
            self._publish_models(result)
        return None

    async def set_thinking_level(self, level: str) -> str | None:
        """Update Pi's persisted thinking level through ACP config options."""
        if self._thinking_config_id is None:
            return "This agent does not advertise thinking-level configuration"
        with self.request():
            response = api.session_set_config_option(
                self.session_id, self._thinking_config_id, level
            )
        try:
            result = await response.wait()
        except (jsonrpc.APIError, jsonrpc.JSONRPCError) as error:
            if isinstance(getattr(error, "data", None), dict):
                details = error.data.get("details") or error.data.get("reason")
                if isinstance(details, str):
                    return details
            return "Failed to set thinking level"
        if result is not None:
            self._publish_models(result)
        return None

    async def get_goal(self) -> Goal | None:
        return (await self.get_goal_snapshot())[0]

    async def get_goal_snapshot(self) -> tuple[Goal | None, GoalExecution | None]:
        if self._coordination_root is None or self._coordination_thread is None:
            return None, None
        async with asyncio.timeout(3):
            result = await self._owner_request("goal_snapshot")
        raw_goal, raw_execution = result["goal"], result["goalExecution"]
        goal = Goal(**raw_goal) if raw_goal is not None else None
        execution = GoalExecution.from_wire(raw_execution) if raw_execution is not None else None
        if execution is not None and (goal is None or execution.goal_id != goal.id):
            raise ValueError("Goal execution identity does not match the owner snapshot.")
        return goal, execution

    async def get_goal_execution(self) -> GoalExecution | None:
        return (await self.get_goal_snapshot())[1]

    async def _owner_request(self, method: str, **params):
        if self._coordination_root is None or self._coordination_thread is None:
            raise ValueError("This action requires an agent-comms thread.")
        from agent_comms.operations import wire
        from agent_comms.runtime import RuntimeProxy, socket_path

        comms = wire(self._coordination_root)
        owner = await asyncio.to_thread(comms.registry.require, self._coordination_thread)
        proxy = RuntimeProxy(self, owner.name, socket_path(comms.root, owner.pid))
        try:
            return await proxy.request(method, **params)
        except RuntimeError as error:
            raise ValueError(str(error)) from error

    async def get_input_delivery(self, *, include_history: bool = False) -> dict:
        if self._coordination_root is None or self._coordination_thread is None:
            return {
                "inputs": [], "historicalCount": 0,
                "dismissedHistoricalCount": 0, "historicalInputs": [],
            }
        return await self._owner_request("input_dispositions", include_history=include_history)

    async def dismiss_historical_inputs(self) -> dict:
        return await self._owner_request("dismiss_historical_inputs")

    async def get_unresolved_inputs(self) -> list[dict]:
        return (await self.get_input_delivery())["inputs"]

    async def get_goal_history(self, goal_id: str):
        result = await self._owner_request("goal_history", goal_id=goal_id)
        return result["history"]

    async def edit_goal(self, goal: Goal, text: str) -> Goal:
        result = await self._owner_request(
            "edit_goal", goal_id=goal.id, expected_revision=goal.revision, text=text
        )
        return Goal(**result["goal"])

    @property
    def transcript_ready(self) -> bool:
        return self._coordination_root is not None and self._coordination_thread is not None

    async def get_transcript_page(
        self, *, before: "TranscriptCursor | None" = None,
        after: "TranscriptCursor | None" = None,
        through: "TranscriptCursor | None" = None,
    ) -> "TranscriptPage":
        from agent_comms import wire

        if self._coordination_root is None or self._coordination_thread is None:
            raise ValueError("Transcript paging requires an agent-comms thread.")
        root, thread = self._coordination_root, self._coordination_thread
        async with self._transcript_reader_lock:
            # Keep the core reader's revision-aware store caches across pages.
            # Recreating Comms for each wheel-driven request reparses the entire
            # routing sidecar even when it has not changed. This retains the
            # service, not a second copy of transcript or routing semantics.
            if self._transcript_reader is None or self._transcript_reader_root != root:
                from toad.app import ToadApp

                # All attachments in one Toad normally use the same wire. Share
                # its existing service so dozens of tabs don't each retain a
                # separately parsed copy of the whole routing sidecar.
                app = self._message_target.app if self._message_target is not None else None
                shared = app.coordination_wire if isinstance(app, ToadApp) else None
                if shared is not None and shared.root == Path(root).expanduser():
                    self._transcript_reader = shared
                else:
                    self._transcript_reader = await asyncio.to_thread(wire, root)
                self._transcript_reader_root = root
            return await asyncio.to_thread(
                self._transcript_reader.thread_transcript_page,
                thread, before=before, after=after, through=through,
            )

    async def update_project(self, path: str) -> str:
        if self._coordination_root is None or self._coordination_thread is None:
            raise ValueError("Project changes require an agent-comms thread.")
        from agent_comms.operations import wire

        result = await asyncio.to_thread(
            wire(self._coordination_root).set_project, self._coordination_thread, path
        )
        self._coordination_worktree = result.current
        self.project_root_path = Path(result.current)
        self._post_coordination_update()
        return result.current

    async def update_goal(self, action: str, text: str = "") -> Goal | None:
        if action == "set":
            result = await self._owner_request("set_goal", text=text)
        else:
            goal, _ = await self.get_goal_snapshot()
            if goal is None:
                raise ValueError("The goal changed; refresh its state.")
            if action == "retry":
                if goal.status != "blocked":
                    raise ValueError("The blocked goal changed; refresh its state.")
                result = await self._owner_request(
                    "retry_goal", goal_id=goal.id, expected_revision=goal.revision
                )
            else:
                result = await self._owner_request(
                    "update_goal", status=action, goal_id=goal.id,
                    expected_revision=goal.revision,
                )
        return Goal(**result["goal"]) if result["goal"] is not None else None

    async def set_session_name(self, name: str) -> None:
        self._pending_session_name = name
        self._rename_coordination_thread(name)
        if self._coordination_thread is not None:
            self._pending_session_name = None
        if self.session_pk is None:
            return
        db = DB()
        await db.session_update_title(self.session_pk, name)

    async def acp_session_cancel(self) -> bool:
        with self.request():
            response = api.session_cancel(self.session_id, {})
        try:
            await response.wait()
        except jsonrpc.APIError:
            # No-op if there is nothing to cancel
            return False
        return True

    async def cancel(self) -> bool:
        return await self.acp_session_cancel()
