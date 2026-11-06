import asyncio
from datetime import datetime
from pathlib import Path

import rich.repr
from agent_comms.acp_extension import (
    InputStartedUpdate,
    PromptRequest,
)
from agent_comms.context_reading import UnmeasuredContext

from toad import paths
from toad.acp.agent_configuration import (
    ModelConfigurationSetting,
    ThinkingConfigurationSetting,
)
from toad.acp.agent_controller import AgentController
from toad.acp.agent_log import AgentLog
from toad.acp.agent_process import AgentProcess
from toad.acp.agent_session import AgentSession
from toad.acp.attachment_presentation import CursorPresentation, QueuePresentation
from toad.acp.client_files import FileClientRequestOwner
from toad.acp.comms_updates import CommsUpdateConsumer
from toad.acp.context_measurement import ContextMeasurement
from toad.acp.permission_controller import PermissionController
from toad.acp.projection_attachment import CursorAttachment
from toad.acp.queue_attachment import QueueAttachment
from toad.acp.session_updates import SessionNotificationOwner
from toad.acp.tool_calls import SessionToolCalls
from toad.acp.transcript_reader import CoordinationTranscriptReader
from toad.acp.session_agent import SessionAgent
from toad.agent_presentation import ACPAgentPresentation
from toad.agent_schema import AgentDefinition
from toad.core import events as core_events
from toad.platform import host
from agent_comms.nominal.field_codec import AcpSessionId


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
class Agent(SessionAgent):
    comms_consumer_class = CommsUpdateConsumer

    @property
    def committed_native_output(self):
        return self.controller.session.output.committed_source

    """An agent that speaks the APC (https://agentclientprotocol.com/overview/introduction) protocol."""

    def __init__(
        self,
        project_root: Path,
        agent: AgentDefinition,
        session_id: AcpSessionId | None,
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
        super().__init__(project_root)
        self.process = AgentProcess(self)
        self.presentation = ACPAgentPresentation(self)
        self.permissions = PermissionController(self)
        self.controller = AgentController(self, transcripts)
        self.tools = SessionToolCalls(self)
        self.definition = agent
        self.session_id = session_id
        self.updates = SessionNotificationOwner(self)
        self.files = FileClientRequestOwner(self)
        self.session = AgentSession(self, session_pk, app_events)
        self.done_event = asyncio.Event()
        self._private_cursor = CursorAttachment()
        self._private_cursor_sequence = 0
        self.queue_attachment = QueueAttachment()
        log_filename: str = generate_datetime_filename(f"{agent.name}", ".txt")
        if (log_path := AgentLog.selected()) is not None:
            self.presentation.log_path = log_path
        else:
            self.presentation.log_path = paths.get_log() / log_filename
        self.context_measurement = ContextMeasurement.saved(UnmeasuredContext())

    @property
    def command(self) -> str | None:
        """The command used to launch the agent, or `None` if there isn't one."""
        return host.select(self.definition.run_command)

    def __rich_repr__(self) -> rich.repr.Result:
        yield self.project_root_path
        yield self.command

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


    async def send_prompt(self, prompt: str, *, request: PromptRequest | None = None):
        """Submit through AgentBase's contract; the controller runs the request."""
        return await self.controller.submit(prompt, request=request)


    @property
    def session_id(self):
        return self.controller.session.session_id

    @session_id.setter
    def session_id(self, value) -> None:
        self.controller.bind_session(value)

    @property
    def ready(self):
        return self.session.ready

    @property
    def current_turn(self):
        return self.presentation.turns.owner

    async def retire_surface(self, surface) -> None:
        if self.controller.surface.owns(surface):
            self.detach_surface(surface)
            await self.stop()

    def attach_surface(self, surface) -> None:
        self.controller.attach(surface)

    def detach_surface(self, surface) -> None:
        self.controller.detach(surface)

    def _post_queue_view(self, starts: tuple[InputStartedUpdate, ...] = ()) -> None:
        self.controller.surface.sync_queue()
        if starts:
            self.events.publish(core_events.CommsUpdated(QueuePresentation(starts), self.session_id))

    def _post_private_cursor(self) -> None:
        self._private_cursor_sequence += 1
        self.events.publish(core_events.CommsUpdated(CursorPresentation(self._private_cursor.status), self.session_id, self._private_cursor_sequence))

    def _invalidate_attachment_views(self) -> None:
        self._private_cursor.invalidate()
        self._post_private_cursor()
        self.queue_attachment.invalidate()
        self._post_queue_view()


    @property
    def available_modes(self):
        return self.configuration.mode.choices

    @property
    def current_mode(self):
        return self.configuration.mode.selected

    async def set_mode(self, mode_id: str) -> str | None:
        return await self.configuration.mode.select(self, mode_id)

    async def set_model(self, model_id: str) -> str | None:
        return await self.configuration.setting(ModelConfigurationSetting).select(self, model_id)

    async def set_thinking_level(self, level: str) -> str | None:
        return await self.configuration.setting(ThinkingConfigurationSetting).select(self, level)

    async def cancel(self) -> bool:
        """AgentBase cancellation contract."""
        return await self.controller.cancel_prompt()

    async def set_session_name(self, name: str) -> None:
        await self.session.set_name(name)
