import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from collections.abc import Container

import rich.repr
from agent_comms.acp_extension import (
    CompactRequest,
    CoordinationChangedUpdate,
    InputStartedUpdate,
    PromptRequest,
    QueuePromptRequest,
)
from agent_comms.context_reading import UnmeasuredContext
from agent_comms.nominal.field_codec import FieldCodec, GoalId, InputId
from agent_comms.goal_actions import GoalAction
from agent_comms.goal_presentation import GoalSnapshot
from agent_comms.goals import Goal, GoalDeclaration
from agent_comms.goal_history import RecordedGoalHistory
from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.session_load import ExistingSessionLoadPlan

from toad import paths
from toad.acp.agent_controller import AgentController
from toad.acp.agent_log import AgentLog
from toad.acp.agent_process import AgentProcess
from toad.acp.agent_session import AgentSession
from toad.acp.session_disposition import SessionDisposition
from toad.acp.attachment_presentation import CursorPresentation, QueuePresentation
from toad.acp.client_files import FileClientRequestOwner
from toad.acp.client_session import ClientSessionRequest
from toad.acp.comms_updates import CommsUpdateConsumer
from toad.acp.coordination_attachment import CoordinationAttachment, CoordinatedThread
from toad.acp.thread_read import ThreadRead
from toad.acp.context_measurement import ContextMeasurement
from toad.acp.permission_controller import PermissionController
from toad.acp.projection_attachment import CursorAttachment
from toad.acp.queue_attachment import QueueAttachment
from toad.acp.session_updates import SessionNotificationOwner
from toad.acp.status import PromptResult
from toad.acp.tool_calls import SessionToolCalls
from toad.acp.transcript_reader import CoordinationTranscriptReader
from toad.agent import AgentBase
from toad.agent_presentation import ACPAgentPresentation
from toad.agent_schema import AgentDefinition
from toad.core import events as core_events
from toad.core_event_carrier import CoreEventMessage
from toad.surface_binding import SurfaceBinding, SurfaceTarget
from toad.compaction_view import CompactionView
from toad.session_start import SessionStartTarget
from toad.status_view import StatusView
from toad.conversation_submission import (
    PromptInputSubmission, ConversationSubmissions, NoSend, SendPending, SendState, SubmissionExecution,
)
from toad.platform import host
from toad.acp.session_agent import SessionAgent


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
class Agent(AgentBase, SessionAgent):
    comms_consumer_class = CommsUpdateConsumer

    @property
    def committed_native_output(self):
        return self.controller.session.output.committed_source

    """An agent that speaks the APC (https://agentclientprotocol.com/overview/introduction) protocol."""

    def __init__(
        self,
        project_root: Path,
        agent: AgentDefinition,
        session_id: str | None,
        session_pk: int | None = None,
        *,
        app_events: core_events.CoreEventStream,
        transcripts: CoordinationTranscriptReader,
    ) -> None:
        """

        Args:
            project_root: Project root path.
            command: Command to launch agent.
        """
        self.definition = agent
        super().__init__(project_root)
        self.process = AgentProcess(self)
        log_filename = generate_datetime_filename(self.definition.name, ".txt")
        if (log_path := AgentLog.selected()) is None:
            log_path = paths.get_log() / log_filename
        self._presentation = ACPAgentPresentation(self, log_path)
        self.permissions = PermissionController(self)
        self.coordination_attachment = CoordinationAttachment()
        self.controller = AgentController(self, transcripts)
        self.tools = SessionToolCalls(self)
        self.controller.bind_session(session_id)
        self.updates = SessionNotificationOwner(self)
        self.files = FileClientRequestOwner(self)
        self.session = AgentSession(self, session_pk, app_events)
        self.done_event = asyncio.Event()
        self._private_cursor = CursorAttachment()
        self._private_cursor_sequence = 0
        self.queue_attachment = QueueAttachment()
        self.context_measurement = ContextMeasurement.saved(UnmeasuredContext())

    @property
    def presentation(self) -> ACPAgentPresentation:
        return self._presentation

    @property
    def session_disposition(self) -> SessionDisposition:
        return self.session.disposition

    def accepts_publication(
        self, message: CoreEventMessage, update: core_events.CommsUpdated
    ) -> bool:
        return message.publisher is self and self.controller.session.session_id == update.session_id

    def borrowed_processes(self) -> tuple[AgentProcess, ...]:
        return (self.process,)

    async def reconnect_session(self, source: SessionStartTarget, plan: ExistingSessionLoadPlan) -> None:
        await self.session.reconnect(plan)

    async def change_project(self, view: StatusView, path: Path) -> None:
        from textual.content import Content

        project = await self.update_project(str(path))
        view.feedback.flash(Content(f"Project changed to {project}"), style="success")

    def request_compaction(self, view: CompactionView, request: CompactRequest) -> None:
        view.compact_context(request)

    async def project_changed(self, path: Path) -> None:
        from toad.db import DB

        await super().project_changed(path)
        if (session_pk := self.session.pk) is not None:
            await DB().session_update_project(session_pk, path)

    def refresh_context(self, view: StatusView) -> None:
        view.thread_status = self.context_measurement.status()

    async def compact_context(self, request: CompactRequest) -> None:
        await self.controller.compact_context(request)

    def __rich_repr__(self) -> rich.repr.Result:
        yield self.project_root_path
        yield host.select(self.definition.run_command)

    def log(self, line: str) -> None:
        """Append a line to this agent's log file (written off the UI thread)."""
        AgentLog.shared().append(self.presentation.log_path, line)

    def get_info(self) -> str:
        return self.definition.name

    async def start(self, processes: tuple[AgentProcess, ...] = ()) -> None:
        """Start the operational agent; attachment resources are acquired separately."""
        await self.process.start(self, processes)

    def update_status_line(self) -> None:
        """The measurement owns availability and source-specific presentation."""
        from toad.core.events import UpdateStatusLine
        self.events.publish(UpdateStatusLine())

    async def stop(self) -> None:
        """Gracefully stop the process."""
        self.session.close()
        await self.controller.terminals.close()
        await self.session.touch()

        await self.process.stop(self)


    def begin_submission(self, owner: ConversationSubmissions, submission: PromptInputSubmission):
        return owner.start(NativeSubmissionExecution(owner, submission, self))

    async def send_prompt(self, prompt: str, *, request: PromptRequest | None = None) -> PromptResult:
        """Decode the public optional request once; the controller requires one."""
        command = request if request is not None else QueuePromptRequest(prompt)
        return await self.controller.submit(prompt, request=command)


    @property
    def ready(self):
        return self.session.ready

    @property
    def current_turn(self):
        return self.presentation.turns.owner

    async def retire_surface(self, surface: SurfaceTarget) -> None:
        if self.controller.surface.owns(surface):
            self.detach_surface(surface)
            await self.stop()

    def attach_surface(self, surface: SurfaceBinding) -> None:
        self.controller.attach(surface)

    def detach_surface(self, surface: SurfaceTarget) -> None:
        self.controller.detach(surface)

    def receive_coordination(self, update: CoordinationChangedUpdate, authority: ClientSessionRequest) -> None:
        """Consume the fact only through its originally captured session authority."""
        authority.require()
        self.controller.transcripts.access.selected(update.wire_root)
        self.coordination_attachment = CoordinatedThread(update)
        self.project_root_path = update.worktree.path
        self.context_measurement = ContextMeasurement.saved(update.context_usage)
        self.update_status_line()
        self.coordination_attachment.publish(self, authority.binding)
        self.session.coordinated_title(update.title)

    def _post_queue_view(self, starts: tuple[InputStartedUpdate, ...] = ()) -> None:
        self.controller.surface.sync_queue()
        if starts:
            publish = self.events.publish
            update = QueuePresentation(starts)
            publish(self.controller.session.publication(update))

    def _post_private_cursor(self) -> None:
        self._private_cursor_sequence += 1
        publish = self.events.publish
        update = CursorPresentation(self._private_cursor.status, self._private_cursor_sequence)
        publish(self.controller.session.publication(update))

    def _invalidate_attachment_views(self) -> None:
        self._private_cursor.invalidate()
        self._post_private_cursor()
        self.queue_attachment.invalidate()
        self._post_queue_view()


    def configuration_refusal(self, label: str) -> str:
        return f"This agent does not advertise {label} configuration"

    async def get_goal_snapshot(self) -> GoalSnapshot:
        """The owner's goal snapshot, read by the observation service; its turn settles here."""
        return await self.coordination_attachment.goal_snapshot(self)

    async def get_goal_history(self, goal_id: GoalId) -> RecordedGoalHistory:
        result = await self.controller.request_owner("goal_history", goal_id=goal_id)
        return FieldCodec.decode(RecordedGoalHistory, result)

    async def edit_goal(self, goal: Goal, text: str) -> Goal:
        result = await self.controller.request_owner(
            "edit_goal", goal_id=goal.id, expected_revision=goal.revision, text=text
        )
        return FieldCodec.decode(Goal, result["goal"])

    @property
    def automatic_titles(self) -> bool:
        return self.coordination_attachment.automatic_titles

    def thread_read(self) -> ThreadRead:
        """Capture, before a presentation read, what its result must still match."""
        return self.coordination_attachment.thread_read(self)

    async def observe_thread_presentation(self, presentation: ThreadPresentation) -> None:
        await self.coordination_attachment.observe_owner(self, presentation)

    async def update_project(self, path: str) -> str:
        return await self.coordination_attachment.update_project(self, path)

    async def update_goal(self, action: type[GoalAction], text: str = "") -> GoalDeclaration:
        result = await action.submit_control(
            self.get_goal_snapshot, self.controller.request_owner, text,
        )
        return FieldCodec.decode(GoalDeclaration, result["goal"])


    async def cancel(self) -> bool:
        """AgentBase cancellation contract."""
        return await self.controller.cancel_prompt()

    async def set_session_name(self, name: str) -> None:
        await self.session.set_name(name)


@dataclass(frozen=True)
class NativeInputPresented(SendState):
    started: InputStartedUpdate

    def response_finished(self, execution: SubmissionExecution) -> None:
        execution.enter(NoSend())


class NativeSubmissionExecution(SubmissionExecution):
    """ACP owns its captured request and native acknowledgement, not the shared transaction."""

    def __init__(self, owner: ConversationSubmissions, submission: PromptInputSubmission, agent: SessionAgent):
        super().__init__(owner, submission)
        self.agent = agent
        self.authority = ClientSessionRequest(agent, agent.controller.session)
        self.scope = agent.queue_attachment.scope
        self.request = submission.request

    @property
    def current(self):
        view = self.owner
        return (view.agent_binding is self.agent and not self.authority.retired
                and self.agent.queue_attachment.accepts_request(self.scope))

    async def feedback(self):
        await self.submission.feedback(self)

    def accepted(self, accepted: Container[InputId]) -> bool:
        return self.request.input_id in accepted or not self.agent.presentation.uses_managed_turns

    def native_input_presented(self, started: InputStartedUpdate) -> None:
        if self.current and started.started_request(self.request.input_id):
            self.state.presented(self, NativeInputPresented(started))

    async def deliver(self):
        view = self.owner
        local = not self.agent.presentation.uses_managed_turns
        if local:
            view.turns.start_client()
        self.enter(SendPending())
        outcome = await self.agent.controller.submit(self.submission.text, request=self.request)
        outcome.settle_submission(self)
        if self.current and local:
            view.call_later(self.complete, outcome)

    async def complete(self, outcome: PromptResult):
        if self.current:
            await outcome.finish_turn(self.owner)
