from toad.acp.context_measurement import ContextMeasurement, ContextUnavailable
from toad.acp.agent_process import AgentProcess
from toad.acp.agent_controller import AgentController
from toad.conversation_turn import AgentTurn, ClientTurn
from toad.acp.permission_controller import PermissionController
from toad.agent_presentation import ACPAgentPresentation
import asyncio
import os
from collections.abc import Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple, cast
from urllib.parse import quote

import rich.repr
from agent_comms.acp_extension import (
    ClearQueueRequest,
    CommsRequest,
    CompactionCommittedUpdate,
    CompactRequest,
    CoordinationChangedUpdate,
    InputFailedUpdate,
    PromptRequest,
    QueueItem,
    SendNowRequest,
    decode_updates,
    encode_request,
)
from agent_comms.acp_failure import ACPFailure, BackendDeliveryFailure
from agent_comms.comms import Comms
from agent_comms.field_codec import FieldCodec
from agent_comms.goal_actions import RetryGoalAction
from agent_comms.goal_presentation import GoalExecution
from agent_comms.goals import Goal
from agent_comms.routing import MessageRoute
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from textual.content import Content
from textual.message import Message
from textual.message_pump import MessagePump

import toad
from toad import constants, jsonrpc, paths
from toad.acp import api, messages, protocol
from toad.acp.api import API
from toad.acp.attachment_presentation import CursorPresentation, QueuePresentation
from toad.acp.comms_updates import CommsUpdateConsumer
from toad.acp.projection_attachment import ProjectionAttachment
from toad.acp.prompt import build as build_prompt
from toad.acp.queue_attachment import QueueAttachment
from toad.acp.sdk_boundary import validate_session_update
from toad.agent import AgentBase, LogAgentFail, UnsupportedResumeAgentFail, AgentReady
from toad.agent_schema import Agent as AgentData
from toad.db import DB, SessionMeta

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
    comms_consumer_class = CommsUpdateConsumer

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
        self.process = AgentProcess(self)
        self.presentation = ACPAgentPresentation(self)
        self.permissions = PermissionController(self)
        self.controller = AgentController(self)
        self._agent_data = agent
        self.session_id = session_id
        self.server = jsonrpc.Server()
        self._session_update_lock = asyncio.Lock()
        self.server.expose_instance(self)
        self._reconnecting = False
        self._connected_ok = False
        self._deferred_submissions: set[asyncio.Task] = set()
        self._pending_session_name: str | None = None
        self._transcript_reader: Comms | None = None
        self._transcript_reader_root: str | None = None
        self._transcript_reader_lock = asyncio.Lock()
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
        self.session_pk: int | None = session_pk
        self.tool_calls: dict[str, protocol.ToolCall] = {}
        self._active_turn_id: str | None = None
        self._turn_lifecycle_sequence = 0
        self._private_cursor = ProjectionAttachment()
        self._private_cursor_sequence = 0
        self.queue_attachment = QueueAttachment()
        self._queue_sequence = 0
        log_filename: str = generate_datetime_filename(f"{agent['name']}", ".txt")
        if log_path := os.environ.get("TOAD_LOG"):
            self.presentation.log_path = Path(log_path).resolve().absolute()
            with suppress(OSError):
                self.presentation.log_path.unlink(missing_ok=True)
        else:
            self.presentation.log_path = paths.get_log() / log_filename
        self._token_usage: TokenUsage | None = None
        self.context_measurement = ContextUnavailable("Native owner has not reported context usage")
        self._model_config_id: str | None = None
        self._thinking_config_id: str | None = None

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
        self.controller.start_operation(self._log(line))

    async def _log(self, line: str) -> None:
        """Write text to the agent log file.

        Intended to be called from `log`

        Args:
            line: Text to be logged.
        """

        def write_log(log_file_path: Path, line: str):
            """Write log in a thread."""
            try:
                with log_file_path.open("at") as log_file:
                    log_file.write(f"{line.rstrip()}\n")
            except OSError:
                pass

        await asyncio.to_thread(write_log, self.presentation.log_path, line)

    def get_info(self) -> Content:
        agent_name = self._agent_data["name"]
        return Content(agent_name)

    async def start(self, message_target: MessagePump | None = None) -> None:
        """Start the agent."""
        if message_target is not None:
            self.attach_surface(message_target)
        try:
            await asyncio.to_thread(
                self.presentation.log_path.parent.mkdir, parents=True, exist_ok=True
            )
        except OSError:
            pass
        await self.process.start()

    def send(self, request: jsonrpc.Request) -> None:
        """Send a request to the agent.

        This is called automatically, if you go through `self.request`.

        Args:
            request: JSONRPC request object.

        """
        self.process.send(request)

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
        return self.controller.surface.post(message)

    @jsonrpc.expose("session/update", ordered=True)
    async def _rpc_session_update(
        self,
        sessionId: str,
        update: Any,
        _meta: dict[str, Any] | None = None,
    ) -> None:
        """Validate wire notifications off-process, then publish to the same owner."""
        session = self.session_id
        async with self._session_update_lock:
            if self.session_id != session or not self.process.accepts_updates:
                return
            validation = await self.controller.validate(sessionId, update, _meta)
            if self.session_id != session or not self.process.accepts_updates:
                return
            if validation.error is not None:
                self._reject_session_update(sessionId, update, _meta, validation.error)
                return
            self._apply_session_update(sessionId, cast(protocol.SessionUpdate, update))

    def rpc_session_update(
        self,
        sessionId: str,
        update: Any,
        _meta: dict[str, Any] | None = None,
    ):
        """Synchronous in-process SDK boundary for direct protocol consumers.

        Wire notifications use the asynchronous process-owned boundary above.
        """
        from pydantic import ValidationError

        try:
            update = validate_session_update(sessionId, update, _meta)
        except ValidationError as error:
            self._reject_session_update(sessionId, update, _meta, str(error))
            return
        self._apply_session_update(sessionId, update)

    def _reject_session_update(self, session_id, update, metadata, error) -> None:
        self.log(
            f"[ACP rejected session/update] raw={{'sessionId': {session_id!r}, "
            f"'update': {update!r}, '_meta': {metadata!r}}}; validation={error}"
        )
        self.post_message(messages.RejectedSessionUpdate())

    def _apply_session_update(
        self, sessionId: str, update: protocol.SessionUpdate
    ) -> None:
        if self.session_id is not None and sessionId != self.session_id:
            return
        metadata = update.get("_meta")
        consumer = self.comms_consumer_class(self, sessionId)
        try:
            facts = decode_updates(metadata)
        except (TypeError, ValueError) as error:
            self._reject_session_update(sessionId, update, metadata, str(error))
            return
        for fact in facts:
            consumer.dispatch_sync(fact)
        route: MessageRoute | None = consumer.route
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
                        text += f"\n\n[Open ACP log]({quote(str(self.presentation.log_path))})"
                    self.post_message(messages.Update(type, text, route))
            case {
                "sessionUpdate": "agent_thought_chunk",
                "content": {"type": type, "text": text},
            }:
                self.post_message(messages.Thinking(type, text))
            case {"sessionUpdate": "tool_call", "toolCallId": tool_call_id}:
                self.tool_calls[tool_call_id] = update
                self.post_message(messages.ToolCall(update))
            case {"sessionUpdate": "plan", "entries": entries}:
                self.post_message(messages.Plan(entries))
            case {"sessionUpdate": "tool_call_update", "toolCallId": tool_call_id}:
                if tool_call_id in self.tool_calls:
                    current_tool_call = self.tool_calls[tool_call_id]
                    for key, value in update.items():
                        if value is not None:
                            current_tool_call[key] = value
                    self.post_message(
                        messages.ToolCallUpdate(deepcopy(current_tool_call), update)
                    )
                else:
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
                self.controller.publish_commands(available_commands)
            case {"sessionUpdate": "current_mode_update", "currentModeId": mode_id}:
                self.controller.current_mode = mode_id
                self.post_message(messages.ModeUpdate(mode_id))
            case {
                "sessionUpdate": "config_option_update",
                "configOptions": config_options,
            }:
                self._publish_models({"configOptions": config_options})
            case {"sessionUpdate": "session_info_update"} if "title" in update:
                title = update.get("title")
                self.post_message(messages.SessionInfoUpdate(title))
            case {"sessionUpdate": "usage_update", "used": used, "size": size}:
                self.context_measurement = ContextMeasurement.live(used, size, update.get("cost"))
                self.update_status_line()

    def update_status_line(self) -> None:
        """The measurement owns availability and source-specific presentation."""
        self.post_message(messages.UpdateStatusLine(self.context_measurement.status()))

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
        cancelled: protocol.RequestPermissionResponse = {
            "outcome": {"outcome": "cancelled"}
        }
        if not self.process.accepts_updates or sessionId != self.session_id:
            return cancelled
        tool_call_id = toolCall["toolCallId"]

        permission_tool_call = cast(dict[str, Any], toolCall.copy())
        permission_tool_call.pop("sessionUpdate", None)
        visible_tool_call: dict[str, Any] = (
            deepcopy(dict(self.tool_calls[tool_call_id]))
            if tool_call_id in self.tool_calls
            else {}
        )
        visible_tool_call.update(permission_tool_call)
        self.tool_calls[tool_call_id] = cast(protocol.ToolCall, deepcopy(visible_tool_call))
        request = self.permissions.request(options, cast(protocol.ToolCallUpdatePermissionRequest, visible_tool_call))
        ask_result = await request.wait(PERMISSION_TIMEOUT_SECONDS)
        if ask_result is None or not self.process.accepts_updates or sessionId != self.session_id:
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
        from toad.terminal_execution import Command

        terminal_env = {variable["name"]: variable["value"] for variable in env} if env else {}
        terminal_id = await self.controller.terminals.create(
            Command(command, args or [], terminal_env, cwd or str(self.project_root_path)),
            outputByteLimit,
        )
        return {"terminalId": terminal_id}

    @jsonrpc.expose("terminal/kill")
    def rpc_terminal_kill(
        self, sessionID: str, terminalId: str, _meta: dict | None = None
    ) -> protocol.KillTerminalCommandResponse:
        self.controller.terminals.kill(terminalId)
        return {}

    @jsonrpc.expose("terminal/output")
    async def rpc_terminal_output(
        self, sessionId: str, terminalId: str, _meta: dict | None = None
    ) -> protocol.TerminalOutputResponse:
        terminal_state = self.controller.terminals.output(terminalId)

        result: protocol.TerminalOutputResponse = {
            "output": terminal_state.output,
            "truncated": terminal_state.truncated,
        }
        if (return_code := terminal_state.return_code) is not None:
            result["exitStatus"] = {"exitCode": return_code}
        return result

    @jsonrpc.expose("terminal/release")
    def rpc_terminal_release(
        self, sessionId: str, terminalId: str, _meta: dict | None = None
    ) -> protocol.ReleaseTerminalResponse:
        self.controller.terminals.release(terminalId)
        return {}

    @jsonrpc.expose("terminal/wait_for_exit")
    async def rpc_terminal_wait_for_exit(
        self, sessionId: str, terminalId: str, _meta: dict | None = None
    ) -> protocol.WaitForTerminalExitResponse:
        return_code, signal = await self.controller.terminals.wait(terminalId)
        return {"exitCode": return_code, "signal": signal}


    async def stop(self) -> None:
        """Gracefully stop the process."""
        await self.controller.terminals.close()
        self.process.close()
        if self.session_pk is not None:
            db = DB()
            await db.session_update_last_used(self.session_pk)

        await self.process.stop()


    async def run(self) -> None:
        """The main logic of the Agent."""
        if constants.ACP_INITIALIZE:
            self._connected_ok = False
            try:
                await self.acp_initialize()
                if self.session_id is None:
                    await self.acp_new_session()
                else:
                    if not self.agent_capabilities.get("loadSession", False):
                        self.post_message(
                            UnsupportedResumeAgentFail(
                                "Resume not supported",
                                f"{self._agent_data['name']} does not currently support resuming sessions.",
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
                self.process.session_failed(ACPFailure.from_error(error.code, error.message, error.data))
                return
        self.session_ready_event.set()
        self.post_message(AgentReady(reconnected=self._reconnecting))

    async def send_prompt(self, prompt: str, *, delivery="queue", defer_display=False):
        return await self.controller.operate(self._send_prompt(
            prompt, delivery=delivery, defer_display=defer_display,
            request_session_id=self.session_id, request_queue_scope=self.queue_attachment.scope,
            project=self.project_root_path))

    async def _send_prompt(
        self, prompt: str, *, delivery: str, defer_display: bool,
        request_session_id, request_queue_scope, project
    ) -> str | None:
        """Send a prompt to the agent.

        !!! note
            This method blocks as it may defer to a thread to read resources.

        Args:
            prompt: Prompt text.
        """
        self.presentation.prompt_in_flight += 1
        submission = asyncio.current_task() if defer_display else None
        if submission is not None:
            self._deferred_submissions.add(submission)
        try:
            prompt_content_blocks = await asyncio.to_thread(
                build_prompt, project, prompt
            )
            if any((block.get("type") == "image" for block in prompt_content_blocks)):
                supported = (
                    True
                    if (self.coordination.wire_root if self.coordination else None)
                    is not None
                    else (self.agent_capabilities.get("promptCapabilities") or {}).get(
                        "image", False
                    )
                )
                if not supported:
                    raise ValueError(
                        "This agent owner does not support images yet; refresh it while idle."
                    )
            request_type = PromptRequest.decode(delivery + "_prompt")
            return await self._acp_session_prompt(
                prompt_content_blocks, request_type(prompt, defer_display),
                request_session_id, request_queue_scope
            )
        finally:
            self.presentation.prompt_in_flight -= 1
            if submission is not None:
                self._deferred_submissions.discard(submission)

    async def clear_queue(self) -> None:
        """Drop prompts still awaiting delivery, leaving the turn running."""
        await self.acp_session_prompt(
            [{"type": "text", "text": " "}], ClearQueueRequest()
        )

    async def send_now(self) -> bool:
        """Interrupt the response for already queued input, without resending text."""
        if pending := tuple(self._deferred_submissions):
            await asyncio.gather(*(asyncio.shield(task) for task in pending))
        result = await self.acp_session_prompt(
            [{"type": "text", "text": " "}], SendNowRequest()
        )
        return result is not None

    async def compact_context(
        self, instructions: str | None = None
    ) -> CompactionCommittedUpdate:
        metadata = encode_request(CompactRequest(instructions))
        with self.request():
            request = api.session_prompt(
                [{"type": "text", "text": " "}], self.session_id, metadata
            )
        try:
            response = await request.wait()
        except jsonrpc.APIError as error:
            failure = ACPFailure.from_error(error.code, error.message, error.data)
            raise ValueError(
                f"{failure.title}: {failure.detail}\n{failure.input_disposition}\n{failure.action}"
            ) from error
        if response is None:
            raise ValueError("Compaction returned no result")
        consumer = self.comms_consumer_class(self, self.session_id)
        for fact in decode_updates(response.get("_meta")):
            consumer.dispatch_sync(fact)
        if consumer.compaction_receipt is None:
            raise ValueError("Compaction result was missing")
        return consumer.compaction_receipt

    async def reconnect_after_auth(self) -> None:
        await self.reconnect()

    async def reconnect(self) -> None:
        """Reattach the existing view after login or an explicit owner start."""
        if self.session_id is not None and not self.supports_load_session:
            raise ValueError("This agent cannot resume its session.")
        from .maintenance_ingress import configured_root, preflight

        requested_env = os.environ.copy()
        requested_cwd = str(self.project_root_path.resolve())
        requested_root = configured_root(requested_env, requested_cwd)
        try:
            await asyncio.to_thread(
                preflight,
                (self.coordination.wire_root if self.coordination else None),
                ingress_root=requested_root,
                cwd=requested_cwd,
            )
        except Exception as error:
            raise ValueError(
                f"Reconnect not attempted: maintenance admission denied: {error}"
            ) from error
        target = self.controller.surface.target
        await self.stop()
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
        self.presentation.auth_methods = response.get("authMethods") or []

    async def acp_new_session(self) -> None:
        """Create a new session."""
        cursor_token = self._private_cursor.begin(None)
        queue_token = self.queue_attachment.begin(None)
        self._post_private_cursor()
        self._post_queue_view()
        with self.request():
            session_new_response = api.session_new(
                str(self.project_root_path),
                [],
            )
        response = await session_new_response.wait()
        if not self._private_cursor.is_current_request(cursor_token):
            return
        assert response is not None
        self.session_id = response["sessionId"]
        self._receive_comms_response(response, cursor_token, queue_token)

        if self.supports_load_session:
            db = DB()
            session_name = (
                self._pending_session_name
                if self._pending_session_name is not None
                else (self.coordination.title if self.coordination else "New Session")
            )
            session_pk = await db.session_new(
                session_name,
                self._agent_data["name"],
                self._agent_data["identity"],
                self.session_id,
                protocol="acp",
                meta=SessionMeta(
                    cwd=self.project_root_path, agent_data=self._agent_data
                ),
            )
            if not self._private_cursor.is_current_request(cursor_token):
                return
            self.session_pk = session_pk
            if self.session_pk is not None and self._pending_session_name is not None:
                await db.session_update_title(
                    self.session_pk, self._pending_session_name
                )

        if not self._private_cursor.is_current_request(cursor_token):
            return
        if (modes := response.get("modes", None)) is not None:
            current_mode = modes["currentModeId"]
            available_modes = modes["availableModes"]
            modes_update = {
                mode["id"]: Mode(
                    mode["id"], mode["name"], mode.get("description", None)
                )
                for mode in available_modes
            }
            self.controller.publish_modes(current_mode, modes_update)
        self._publish_models(response)

    async def acp_load_session(self) -> None:
        assert self.session_id is not None, "Session id must be set"
        request_session_id = self.session_id
        cursor_token = self._private_cursor.begin(request_session_id)
        queue_token = self.queue_attachment.begin(request_session_id)
        self._post_private_cursor()
        self._post_queue_view()
        cwd = str(self.project_root_path)
        if self.session_pk is not None:
            db = DB()
            session = await db.session_get(self.session_pk)
            if not self._private_cursor.is_current_request(cursor_token):
                return
            if session is not None:
                if session_cwd := session.meta_json.cwd:
                    cwd = str(session_cwd)
                if agent_data := session.meta_json.agent_data:
                    self._agent_data = agent_data

        with self.request():
            session_load_response = api.session_load(cwd, [], request_session_id)
        response = await session_load_response.wait()
        if (
            not self._private_cursor.is_current_request(cursor_token)
            or self.session_id != request_session_id
        ):
            return
        assert response is not None
        self._receive_comms_response(response, cursor_token, queue_token)

        if (modes := response.get("modes", None)) is not None:
            current_mode = modes["currentModeId"]
            available_modes = modes["availableModes"]
            modes_update = {
                mode["id"]: Mode(
                    mode["id"], mode["name"], mode.get("description", None)
                )
                for mode in available_modes
            }
            self.controller.publish_modes(current_mode, modes_update)
        self._publish_models(response)

    def _publish_models(self, response: Mapping[str, object]) -> None:
        """Publish the current model and thinking-level config options."""
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
                    self.controller.publish_models(current, models)
                elif config.get("id") == "thinking_level":
                    levels = [
                        str(option["value"])
                        for option in options
                        if isinstance(option.get("value"), str)
                    ]
                    if current in levels:
                        self._thinking_config_id = str(config["id"])
                        self.presentation.current_thinking_level = current
                        self.presentation.thinking_levels = levels
                        self.post_message(messages.SetThinkingLevels(current, levels))
            if self._model_config_id is None:
                self.controller.publish_models("", {})
            return

    @property
    def session_id(self):
        return self.controller.session_id

    @session_id.setter
    def session_id(self, value):
        if value != self.controller.session_id:
            self.controller.replace_terminal_session()
            self.permissions.cancel()
            self._active_turn_id = None
            self.controller.session_id = value

    @property
    def ready(self):
        return self._connected_ok and self.session_ready_event.is_set()

    @property
    def current_turn(self):
        return AgentTurn(self._active_turn_id) if self._active_turn_id else ClientTurn()

    async def retire_surface(self, surface):
        if self.controller.surface.owns(surface):
            self.detach_surface(surface)
            await self.stop()

    def attach_surface(self, surface) -> None:
        self.controller.attach(surface)

    def detach_surface(self, surface) -> None:
        self.controller.detach(surface)

    @property
    def coordination(self) -> CoordinationChangedUpdate | None:
        return self.controller.coordination

    @coordination.setter
    def coordination(self, value: CoordinationChangedUpdate | None) -> None:
        self.controller.coordination = value

    def _receive_comms_response(
        self, response, cursor_token: int, queue_token: int
    ) -> None:
        consumer = self.comms_consumer_class(
            self, self.session_id, cursor_token=cursor_token, queue_token=queue_token
        )
        for fact in decode_updates(response.get("_meta")):
            consumer.dispatch_sync(fact)

    def _post_queue_view(self, starts: tuple[QueueItem, ...] = ()) -> None:
        self._queue_sequence += 1
        self.post_message(
            messages.CommsUpdated(
                QueuePresentation(self.queue_attachment.projection, starts),
                self,
                self.session_id,
                self._queue_sequence,
            )
        )

    def _post_private_cursor(self) -> None:
        self._private_cursor_sequence += 1
        self.post_message(
            messages.CommsUpdated(
                CursorPresentation(self._private_cursor.status),
                self,
                self.session_id,
                self._private_cursor_sequence,
            )
        )

    def _invalidate_attachment_views(self) -> None:
        self._private_cursor.invalidate()
        self._post_private_cursor()
        self.queue_attachment.invalidate()
        self._post_queue_view()

    def _rename_coordination_thread(self, display_name: str) -> None:
        thread = self.coordination.thread.name if self.coordination else None
        wire_root = self.coordination.wire_root if self.coordination else None
        process = self.process.process
        if thread is None or wire_root is None or process is None:
            return

        from agent_comms.comms import wire

        result = wire(wire_root).threads.rename_managed_thread(
            thread,
            display_name,
            owner_pid=self.coordination.owner_pid,
        )
        self.coordination = replace(
            self.coordination,
            thread=replace(self.coordination.thread, name=result.current),
            title=display_name,
        )
        self.post_message(
            messages.CommsUpdated(self.coordination, self, self.session_id)
        )

    async def acp_session_prompt(self, prompt, command=None):
        return await self.controller.operate(self._acp_session_prompt(
            prompt, command, self.session_id, self.queue_attachment.scope))

    async def _acp_session_prompt(
        self, prompt: list[protocol.ContentBlock], command: CommsRequest | None,
        request_session_id, request_queue_scope
    ) -> str | None:
        """Send the prompt to the agent.

        Returns:
            The stop reason.

        """
        with self.request():
            session_prompt = api.session_prompt(
                prompt,
                request_session_id,
                encode_request(command) if command is not None else {},
            )
        try:
            result = await session_prompt.wait()
        except jsonrpc.APIError as error:
            failure = ACPFailure.from_error(error.code, error.message, error.data)
            user_text = command.draft_text if command is not None else None
            if isinstance(user_text, str) and user_text:
                self.post_message(
                    messages.CommsUpdated(
                        InputFailedUpdate(user_text, failure),
                        recover_draft=True,
                        agent=self,
                        session_id=request_session_id,
                        queue_scope=request_queue_scope,
                    )
                )
            self.post_message(
                LogAgentFail(
                    failure.title,
                    f"{failure.detail}\n{failure.input_disposition}\n{failure.action}",
                    log_path=self.presentation.log_path,
                )
            )
            return None
        except jsonrpc.JSONRPCError as error:
            user_text = command.draft_text if command is not None else None
            if isinstance(user_text, str) and user_text:
                self.post_message(
                    messages.CommsUpdated(
                        InputFailedUpdate(
                            user_text,
                            BackendDeliveryFailure(
                                error.message or "Connection failed"
                            ),
                        ),
                        recover_draft=True,
                        agent=self,
                        session_id=request_session_id,
                        queue_scope=request_queue_scope,
                    )
                )
            self.post_message(
                LogAgentFail(
                    "Failed to send prompt",
                    error.message or f"{self._agent_data['name']} returned an error",
                    log_path=self.presentation.log_path,
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
            return ACPFailure.from_error(error.code, error.message, error.data).feedback
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
        except jsonrpc.APIError as error:
            return ACPFailure.from_error(error.code, error.message, error.data).feedback
        except jsonrpc.JSONRPCError as error:
            return ACPFailure.from_error(error.code, error.message).feedback
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
        except jsonrpc.APIError as error:
            return ACPFailure.from_error(error.code, error.message, error.data).feedback
        except jsonrpc.JSONRPCError as error:
            return ACPFailure.from_error(error.code, error.message).feedback
        if result is not None:
            self._publish_models(result)
        return None

    async def get_goal(self) -> Goal | None:
        return (await self.get_goal_snapshot())[0]

    async def get_goal_snapshot(self) -> tuple[Goal | None, GoalExecution | None]:
        if (self.coordination.wire_root if self.coordination else None) is None or (
            self.coordination.thread.name if self.coordination else None
        ) is None:
            return None, None
        async with asyncio.timeout(3):
            result = await self._owner_request("goal_snapshot")
        raw_goal, raw_execution = result["goal"], result["goalExecution"]
        goal = FieldCodec.decode(Goal, raw_goal) if raw_goal is not None else None
        execution = (
            GoalExecution.from_wire(raw_execution)
            if raw_execution is not None
            else None
        )
        if execution is not None and (goal is None or execution.goal_id != goal.id):
            raise ValueError(
                "Goal execution identity does not match the owner snapshot."
            )
        return goal, execution

    async def get_goal_execution(self) -> GoalExecution | None:
        return (await self.get_goal_snapshot())[1]

    async def _owner_request(self, method: str, **params):
        if (self.coordination.wire_root if self.coordination else None) is None or (
            self.coordination.thread.name if self.coordination else None
        ) is None:
            raise ValueError("This action requires an agent-comms thread.")
        from agent_comms.runtime import RuntimeProxy, socket_path

        root, thread = (
            (self.coordination.wire_root if self.coordination else None),
            (self.coordination.thread.name if self.coordination else None),
        )
        async with self._transcript_reader_lock:
            comms = await self._get_coordination_reader(root)

            def resolve():
                from toad.owner_preparation import OwnerRequestContext

                owner = comms.registry.require(thread)
                # RuntimeProxy normally creates another wire when its caller
                # has no service. Capture the existing service instead of
                # reparsing the entire registry for each status poll.
                return RuntimeProxy(
                    OwnerRequestContext(comms),
                    owner.name,
                    socket_path(comms.root, owner.pid),
                )

            proxy = await asyncio.to_thread(resolve)
        try:
            if (root, thread) != (
                (self.coordination.wire_root if self.coordination else None),
                (self.coordination.thread.name if self.coordination else None),
            ):
                raise ValueError(
                    "The owner identity changed while preparing the request."
                )
            return await proxy.request(method, **params)
        except RuntimeError as error:
            raise ValueError(str(error)) from error
        finally:
            await proxy.close()

    async def get_input_delivery(self, *, include_history: bool = False) -> dict:
        if (self.coordination.wire_root if self.coordination else None) is None or (
            self.coordination.thread.name if self.coordination else None
        ) is None:
            return {
                "inputs": [],
                "historicalCount": 0,
                "dismissedHistoricalCount": 0,
                "historicalInputs": [],
            }
        return await self._owner_request(
            "input_dispositions", include_history=include_history
        )

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
        return FieldCodec.decode(Goal, result["goal"])

    @property
    def transcript_ready(self) -> bool:
        return (
            self.coordination.wire_root if self.coordination else None
        ) is not None and (
            self.coordination.thread.name if self.coordination else None
        ) is not None

    async def _get_coordination_reader(self, root: str) -> Comms:
        """Use under the reader lock; initialization and registry I/O stay off-loop."""
        from agent_comms.comms import wire

        from toad.app import ToadApp

        if self._transcript_reader is None or self._transcript_reader_root != root:
            app = self.controller.app
            shared = app._coordination_wire if isinstance(app, ToadApp) else None
            if shared is not None and shared.root == Path(root).expanduser():
                self._transcript_reader = shared
            else:
                self._transcript_reader = await asyncio.to_thread(wire, root)
            self._transcript_reader_root = root
        return self._transcript_reader

    async def get_thread_presentation(self):
        from toad.owner_preparation import read_thread_presentation

        root, thread = (
            (self.coordination.wire_root if self.coordination else None),
            (self.coordination.thread.name if self.coordination else None),
        )
        if root is None or thread is None:
            return None
        async with self._transcript_reader_lock:
            reader = await self._get_coordination_reader(root)
            presentation = await asyncio.to_thread(
                read_thread_presentation, reader, thread
            )
        if (root, thread) != (
            (self.coordination.wire_root if self.coordination else None),
            (self.coordination.thread.name if self.coordination else None),
        ):
            raise ValueError("Thread attachment changed while reading status")
        return presentation

    async def get_transcript_page(
        self,
        *,
        before: "TranscriptCursor | None" = None,
        after: "TranscriptCursor | None" = None,
        through: "TranscriptCursor | None" = None,
    ) -> "TranscriptPage":
        if (self.coordination.wire_root if self.coordination else None) is None or (
            self.coordination.thread.name if self.coordination else None
        ) is None:
            raise ValueError("Transcript paging requires an agent-comms thread.")
        root, thread = (
            (self.coordination.wire_root if self.coordination else None),
            (self.coordination.thread.name if self.coordination else None),
        )
        async with self._transcript_reader_lock:
            reader = await self._get_coordination_reader(root)
            return await asyncio.to_thread(
                reader.transcripts.thread_transcript_page,
                thread,
                before=before,
                after=after,
                through=through,
            )

    async def update_project(self, path: str) -> str:
        if (self.coordination.wire_root if self.coordination else None) is None or (
            self.coordination.thread.name if self.coordination else None
        ) is None:
            raise ValueError("Project changes require an agent-comms thread.")
        from agent_comms.comms import wire

        result = await asyncio.to_thread(
            wire(
                (self.coordination.wire_root if self.coordination else None)
            ).threads.set_project,
            (self.coordination.thread.name if self.coordination else None),
            path,
        )
        self.coordination = replace(self.coordination, worktree=result.current)
        self.project_root_path = Path(result.current)
        self.post_message(
            messages.CommsUpdated(self.coordination, self, self.session_id)
        )
        return result.current

    async def update_goal(self, action: str, text: str = "") -> Goal | None:
        if action == "set":
            result = await self._owner_request("set_goal", text=text)
        else:
            goal, _ = await self.get_goal_snapshot()
            if goal is None:
                raise ValueError("The goal changed; refresh its state.")
            if action == "retry":
                if goal.state.toggle is not RetryGoalAction:
                    raise ValueError("The blocked goal changed; refresh its state.")
                result = await self._owner_request(
                    "retry_goal", goal_id=goal.id, expected_revision=goal.revision
                )
            else:
                result = await self._owner_request(
                    "update_goal",
                    status=action,
                    goal_id=goal.id,
                    expected_revision=goal.revision,
                )
        return (
            FieldCodec.decode(Goal, result["goal"])
            if result["goal"] is not None
            else None
        )

    async def set_session_name(self, name: str) -> None:
        self._pending_session_name = name
        self._rename_coordination_thread(name)
        if (self.coordination.thread.name if self.coordination else None) is not None:
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
