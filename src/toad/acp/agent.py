from toad.acp.agent_session import AgentSession
from toad.acp.session_updates import SessionNotificationOwner
from toad.acp.client_session import ClientRequestOwner
from toad.acp.client_files import FileClientRequestOwner
from toad.acp.tool_calls import SessionToolCalls
from toad.acp.agent_configuration import ModelConfigurationSetting, ThinkingConfigurationSetting
from toad.acp.context_measurement import ContextMeasurement, ContextUnavailable
from toad.acp.agent_process import AgentProcess
from toad.acp.agent_controller import AgentController
from toad.acp.permission_controller import PermissionController
from toad.agent_presentation import ACPAgentPresentation
import asyncio
import os
from contextlib import suppress
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import rich.repr
from agent_comms.acp_extension import (
    CoordinationChangedUpdate,
    PromptRequest,
    InputStartedUpdate,
    decode_updates,
)
from agent_comms.acp_failure import ACPFailure
from agent_comms.field_codec import FieldCodec
from agent_comms.goal_actions import RetryGoalAction
from agent_comms.goal_presentation import GoalExecution
from agent_comms.goals import Goal
from agent_comms.transcripts import TranscriptCursor, TranscriptPage, TranscriptReadIdentity
from textual.content import Content
from textual.message import Message
from textual.message_pump import MessagePump

import toad
from toad import jsonrpc, paths
from toad.core import events as messages
from toad.acp.api import API
from toad.acp.attachment_presentation import CursorPresentation, QueuePresentation
from toad.acp.comms_updates import CommsUpdateConsumer
from toad.acp.projection_attachment import ProjectionAttachment
from toad.acp.queue_attachment import QueueAttachment
from toad.core.events import UnsupportedResumeAgentFail, AgentReady
from toad.agent import AgentBase
from toad.agent_schema import AgentDefinition


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
        agent: AgentDefinition,
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
        self.tools = SessionToolCalls(self)
        self.definition = agent
        self.session_id = session_id
        self.server = jsonrpc.Server()
        self.updates = SessionNotificationOwner(self)
        self.server.expose_instance(self)
        for owner in ClientRequestOwner.members_with(ClientRequestOwner):
            self.server.expose_instance(owner.resolve(self))
        self.session = AgentSession(self, session_pk)
        self.done_event = asyncio.Event()
        self._private_cursor = ProjectionAttachment()
        self._private_cursor_sequence = 0
        self.queue_attachment = QueueAttachment()
        log_filename: str = generate_datetime_filename(f"{agent.name}", ".txt")
        if log_path := os.environ.get("TOAD_LOG"):
            self.presentation.log_path = Path(log_path).resolve().absolute()
            with suppress(OSError):
                self.presentation.log_path.unlink(missing_ok=True)
        else:
            self.presentation.log_path = paths.get_log() / log_filename
        self.context_measurement = ContextUnavailable("Native owner has not reported context usage")

    @property
    def command(self) -> str | None:
        """The command used to launch the agent, or `None` if there isn't one."""
        acp_command = toad.get_os_matrix(self.definition.run_command)
        return acp_command

    @property
    def supports_load_session(self) -> bool:
        """Does the agent support loading sessions?"""
        return self.session.supports_load

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
        agent_name = self.definition.name
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

    def update_status_line(self) -> None:
        """The measurement owns availability and source-specific presentation."""
        from toad.core.events import UpdateStatusLine
        self.events.publish(UpdateStatusLine())

    async def stop(self) -> None:
        """Gracefully stop the process."""
        self.process.close()
        await self.controller.terminals.close()
        await self.session.touch()

        await self.process.stop()


    async def send_prompt(self, prompt: str, *, request: PromptRequest | None = None):
        """AgentBase submission contract, executed by operational custody."""
        return await self.controller.submit(prompt, request=request)


    @property
    def session_id(self):
        return self.controller.session.session_id

    @session_id.setter
    def session_id(self, value):
        self.controller.bind_session(value)

    @property
    def ready(self):
        return self.session.ready

    @property
    def current_turn(self):
        return self.presentation.turns.owner

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

    def _receive_comms_metadata(
        self, metadata, cursor_token: int, queue_token: int, turn_token: int | None = None,
        *, consumer_class=None,
    ) -> None:
        consumer = (consumer_class or self.comms_consumer_class)(
            self, self.session_id, cursor_token=cursor_token, queue_token=queue_token,
            turn_token=turn_token,
        )
        for fact in decode_updates(metadata):
            consumer.dispatch_sync(fact)

    def _post_queue_view(self, starts: tuple[InputStartedUpdate, ...] = ()) -> None:
        self.events.publish(messages.CommsUpdated(QueuePresentation(starts), self.session_id))

    def _post_private_cursor(self) -> None:
        self._private_cursor_sequence += 1
        self.events.publish(messages.CommsUpdated(CursorPresentation(self._private_cursor.status), self.session_id, self._private_cursor_sequence))

    def _invalidate_attachment_views(self) -> None:
        self._private_cursor.invalidate()
        self._post_private_cursor()
        self.queue_attachment.invalidate()
        self._post_queue_view()


    @property
    def available_modes(self):
        return self.controller.available_modes

    @property
    def current_mode(self):
        return self.controller.current_mode

    async def set_mode(self, mode_id: str) -> str | None:
        return await self.session.set_mode(mode_id)

    async def set_model(self, model_id: str) -> str | None:
        return await self.configuration.setting(ModelConfigurationSetting).select(self, model_id)

    async def set_thinking_level(self, level: str) -> str | None:
        return await self.configuration.setting(ThinkingConfigurationSetting).select(self, level)

    async def get_goal(self) -> Goal | None:
        return (await self.get_goal_snapshot())[0]

    async def get_goal_snapshot(self) -> tuple[Goal | None, GoalExecution | None]:
        from .comms_updates import OwnerSnapshotConsumer
        if (self.coordination.wire_root if self.coordination else None) is None or (
            self.coordination.thread.name if self.coordination else None
        ) is None:
            return None, None
        async with asyncio.timeout(3):
            turn_token = self.presentation.turns.sequence
            result = await self.controller.request_owner("goal_snapshot")
        self._receive_comms_metadata(result.get("_meta"), None,
                                     None, turn_token,
                                     consumer_class=OwnerSnapshotConsumer)
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

    async def get_goal_history(self, goal_id: str):
        result = await self.controller.request_owner("goal_history", goal_id=goal_id)
        return result["history"]

    async def edit_goal(self, goal: Goal, text: str) -> Goal:
        result = await self.controller.request_owner(
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

    async def get_thread_presentation(self):
        from toad.owner_preparation import read_thread_presentation

        root, thread = (
            (self.coordination.wire_root if self.coordination else None),
            (self.coordination.thread.name if self.coordination else None),
        )
        if root is None or thread is None:
            return None
        async with self.controller.transcripts.bind(root) as reader:
            presentation = await asyncio.to_thread(
                read_thread_presentation, reader, thread
            )
        if (root, thread) != (
            (self.coordination.wire_root if self.coordination else None),
            (self.coordination.thread.name if self.coordination else None),
        ):
            raise ValueError("Thread attachment changed while reading status")
        return presentation

    async def get_message_notifications(self, references):
        coordination = self.coordination
        if coordination is None:
            return {}
        results = await self.controller.transcripts.notifications(coordination.wire_root, references)
        if self.coordination is None or self.coordination.wire_root != coordination.wire_root:
            raise ValueError("Thread attachment changed during original-message notification read")
        return results

    async def observe_thread_presentation(self, presentation) -> None:
        await self.session.observe_owner(presentation)

    async def get_transcript_page(
        self,
        *,
        before: "TranscriptCursor | None" = None,
        after: "TranscriptCursor | None" = None,
        through: "TranscriptCursor | None" = None,
        read_identity: "TranscriptReadIdentity | None" = None,
    ) -> "TranscriptPage":
        if (self.coordination.wire_root if self.coordination else None) is None or (
            self.coordination.thread.name if self.coordination else None
        ) is None:
            raise ValueError("Transcript paging requires an agent-comms thread.")
        root, thread = (
            (self.coordination.wire_root if self.coordination else None),
            (self.coordination.thread.name if self.coordination else None),
        )
        page = await self.controller.transcripts.page(
            root, thread, before=before, after=after, through=through,
            read_identity=read_identity,
        )
        if (root, thread) != (
            (self.coordination.wire_root if self.coordination else None),
            (self.coordination.thread.name if self.coordination else None),
        ):
            raise ValueError("Thread attachment changed while reading transcript")
        return page

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
        self.events.publish(messages.CommsUpdated(self.coordination, self.session_id))
        return result.current

    async def update_goal(self, action: str, text: str = "") -> Goal | None:
        if action == "set":
            result = await self.controller.request_owner("set_goal", text=text)
        else:
            goal, _ = await self.get_goal_snapshot()
            if goal is None:
                raise ValueError("The goal changed; refresh its state.")
            if action == "retry":
                if goal.state.toggle is not RetryGoalAction:
                    raise ValueError("The blocked goal changed; refresh its state.")
                result = await self.controller.request_owner(
                    "retry_goal", goal_id=goal.id, expected_revision=goal.revision
                )
            else:
                result = await self.controller.request_owner(
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


    async def cancel(self) -> bool:
        """AgentBase cancellation contract."""
        return await self.controller.cancel_prompt()

    async def set_session_name(self, name: str) -> None:
        await self.session.set_name(name)
