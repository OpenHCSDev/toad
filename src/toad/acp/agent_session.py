"""ACP session handshake, durable metadata and reconnection."""
from __future__ import annotations
from agent_comms.declared_family import DeclaredFamily
from agent_comms.child_process import join_retirement
import asyncio
import os
from pathlib import Path
from dataclasses import dataclass, replace
from collections.abc import Callable
from agent_comms.acp_ingress import AcpIngress
from agent_comms.errors import RelationViolationError
from agent_comms.route_selection import RouteChanged, RouteSelection
from agent_comms.thread_presentation import SessionDisconnected
import toad
from toad import constants
from acp.exceptions import RequestError
from toad.core import events as core_events
from acp import schema
from toad.acp.client_session import ClientSessionRequest
from toad.core.events import AgentFail, AgentReady, UnsupportedResumeAgentFail, LogAgentFail
from toad.db import DB, SessionMeta
from agent_comms.acp_failure import ACPFailure
from agent_comms.acp_extension import HistoryOnlyQueueProjection
from agent_comms.input_attempt import NotSentInput
from agent_comms.owner_protocol import IncompatibleOwner
from agent_comms.session_load import EnsuringSessionLoadPlan, ExistingSessionLoadPlan, FailedSessionLoadPlan, SessionLoadPlan

PROTOCOL_VERSION = 1


class SessionDisposition(DeclaredFamily, affix="SessionDisposition"):
    accepts_updates = False
    # Whether the agent process may hold this session, so that leaving a
    # shared process has to ask it to close the session.
    held_by_agent = True

    @staticmethod
    def of(agent) -> "SessionDisposition":
        """A view that has not started an agent holds no session."""
        return UnopenedSessionDisposition() if agent is None else agent.session.disposition

    def close(self, agent):
        return self

    def present[T](self, ordinary: T, show: Callable[[SessionDisconnected], T]) -> T:
        """One session presentation, projected into a row or an input notice."""
        return ordinary

    async def present_failure(self, failure: AgentFail, view) -> None:
        await failure.present(view)


class UnopenedSessionDisposition(SessionDisposition):
    held_by_agent = False


class UnavailableSessionDisposition(SessionDisposition):
    status: SessionDisconnected

    def present[T](self, ordinary: T, show: Callable[[SessionDisconnected], T]) -> T:
        return show(self.status)


@dataclass(frozen=True)
class ActiveSessionDisposition(SessionDisposition):
    session: AgentSession
    accepts_updates = True

    def present[T](self, ordinary: T, show: Callable[[SessionDisconnected], T]) -> T:
        return ordinary if self.session.ready else show(SessionDisconnected("Connecting to agent…"))

    def close(self, agent):
        agent.controller.connection_closed()
        return ClosedSessionDisposition()


class ClosedSessionDisposition(UnavailableSessionDisposition):
    status = SessionDisconnected("Session closed. Your draft is kept.")


@dataclass(frozen=True)
class HistoryOnlySessionDisposition(UnavailableSessionDisposition, ActiveSessionDisposition):
    """The thread's owner runs another Core: its history is open, its input refused."""

    owner: IncompatibleOwner

    @property
    def status(self) -> SessionDisconnected:
        return SessionDisconnected(self.owner.line())


@dataclass(frozen=True)
class FailedSessionDisposition(UnavailableSessionDisposition):
    """The session's current terminal failure, retained by its lifecycle owner."""

    failure: AgentFail

    @property
    def status(self) -> SessionDisconnected:
        return SessionDisconnected(self.failure.message)

    async def present_failure(self, failure: AgentFail, view) -> None:
        if failure is self.failure:
            await failure.present_session(view)
        else:
            await super().present_failure(failure, view)


class RefusedSessionDisposition(FailedSessionDisposition):
    """The agent process answered the handshake with an error; it holds no session."""

    held_by_agent = False


class LoginNotReady(ValueError):
    """A terminal login finished, but the session it restarted did not become ready."""


class AgentSession:
    """Own readiness and durable session effects; binding identity stays on the controller."""

    reconnect_timeout_seconds = 30

    def __init__(self, agent, pk, app_events: core_events.CoreEventStream):
        self.agent = agent
        # The app's stream: its thread rows show this session's state, attached to a view or not.
        self.app_events = app_events
        self.task = None
        self.responses = set()
        self.retirement = None
        self._disposition: SessionDisposition = ActiveSessionDisposition(self)
        self.pk = pk
        self.chosen_name = None
        self.connected = False
        self.reconnecting = False
        self.load_plan: SessionLoadPlan = EnsuringSessionLoadPlan()
        self.settled = asyncio.Event()

    @property
    def disposition(self) -> SessionDisposition:
        return self._disposition

    @disposition.setter
    def disposition(self, state: SessionDisposition) -> None:
        if state is not self._disposition:
            self._disposition = state
            self.app_events.publish(core_events.ThreadRowStateChanged())

    @property
    def capabilities(self):
        response = self.agent.process.initialization
        return (response.agent_capabilities if response is not None
                and response.agent_capabilities is not None else schema.AgentCapabilities())

    @property
    def accepts_updates(self):
        return self.disposition.accepts_updates

    def accepts_session(self, session_id: str | None) -> bool:
        """Only this active session may consume work for its current binding."""
        return self.accepts_updates and self.agent.session_id == session_id

    def start_operation(self, operation):
        task = asyncio.create_task(operation)
        if not self.accepts_updates:
            task.cancel()
        self.responses.add(task)
        task.add_done_callback(self.responses.discard)
        return task

    def close(self):
        self.disposition = self.disposition.close(self.agent)

    def reopen(self):
        self.disposition = ActiveSessionDisposition(self)
        self.retirement = None

    def start(self):
        self.task = asyncio.create_task(self.run())
        self.task.add_done_callback(self.session_finished)

    def begin_retirement(self):
        self.close()
        if self.retirement is None:
            self.retirement = asyncio.create_task(self._retire())
            self.retirement.add_done_callback(self.retirement_finished)
        return self.retirement

    async def retire(self):
        await join_retirement(self.begin_retirement())

    async def _retire(self):
        pending = tuple(task for task in (self.task, *self.responses)
                        if task is not None)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.responses.clear()
        self.task = None
        await self.agent.process.detach(self)

    def session_finished(self, task):
        if task.cancelled():
            return
        error = task.exception()
        if error is not None and self.accepts_updates:
            self.startup_failed(f"{type(error).__name__}: {error}")

    def retirement_finished(self, task):
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self.agent.log(f"[error] Session retirement failed: {error}")

    def record_failure(
        self,
        event: AgentFail,
        state: type[FailedSessionDisposition] = FailedSessionDisposition,
    ) -> None:
        """Retain and publish every terminal failure through the session owner."""
        self.close()
        self.settled.set()
        self.disposition = state(event)
        self.agent.events.publish(event)
        self.begin_retirement()

    def session_failed(self, failure):
        self.record_failure(
            LogAgentFail(failure.title, failure.feedback, log_path=self.agent.presentation.log_path),
            RefusedSessionDisposition,
        )

    def startup_failed(self, details):
        self.record_failure(
            LogAgentFail("ACP session startup failed", details=details,
                         log_path=self.agent.presentation.log_path),
            FailedSessionDisposition,
        )

    @property
    def supports_images(self):
        prompt = self.capabilities.prompt_capabilities
        return prompt is not None and prompt.image

    @property
    def ready(self):
        return self.connected and self.settled.is_set()

    @property
    def supports_load(self):
        return self.capabilities.load_session

    def starting(self):
        """Starting clears readiness before any asynchronous work."""
        self.connected = False
        self.settled.clear()
        self.agent.controller.reset_configuration()

    def closed(self):
        self.connected = False

    async def touch(self):
        if self.pk is not None:
            await DB().session_update_last_used(self.pk)

    def coordinated_title(self, title):
        """A coordination update presents the thread's title.

        A name the user chose wins: it is announced as the session's title
        and carried to the wire when the wire does not already carry it.
        Otherwise the saved title and the tab follow the thread's title.
        """
        from toad.core.events import SessionInfoUpdate, SessionThreadTitle
        self.agent.events.publish(SessionInfoUpdate(self.chosen_name or title))
        if self.chosen_name is not None:
            coordination = self.agent.coordination
            if coordination is not None and coordination.title != self.chosen_name:
                self.start_operation(self.rename_coordination(self.chosen_name))
            return
        if title:
            self.agent.events.publish(SessionThreadTitle(title))
            if self.pk is not None:
                self.start_operation(self._adopt_thread_title(title))

    async def _adopt_thread_title(self, title):
        """A session without a chosen name keeps its saved title following the thread."""
        await DB().session_update_title(self.pk, title)

    async def run(self) -> None:
        """The main logic of the Agent."""
        if constants.ACP_INITIALIZE:
            self.connected = False
            try:
                await self.initialize()
                if self.agent.controller.session.bound:
                    if not self.supports_load:
                        self.record_failure(UnsupportedResumeAgentFail(
                            "Resume not supported",
                            f"{self.agent.definition.name} does not currently support resuming sessions.",
                        ))
                        return
                    await self.load()
                    await self.touch()
                else:
                    await self.new()
                self.connected = True
            except RequestError as error:
                # The handshake has not accepted a prompt, regardless of the
                # server's reason for refusing this attachment.
                failure = replace(ACPFailure.from_error(error.code, error.message, error.data),
                                  input_state=NotSentInput)
                self.session_failed(failure)
                return
        self.settled.set()
        self.app_events.publish(core_events.ThreadRowStateChanged())
        self.agent.events.publish(AgentReady(session_id=self.agent.session_id, reconnected=self.reconnecting))


    async def observe_owner(self, presentation) -> None:
        """Load again when Core shows a newer owner process than the one this session loaded.

        A restarted owner answers through the still-open connection, but the queue
        and cursor views are bound to the process named in the load response and
        refuse the new one's updates until a new load binds them.
        """
        if not self.settled.is_set() or self.reconnecting or presentation is None:
            return
        if self.agent.coordination is None:
            return
        binding = presentation.binding
        if not self.load_plan.superseded_by(binding):
            return
        await self.reconnect(ExistingSessionLoadPlan(binding))

    async def reconnect(self, plan: SessionLoadPlan | None = None) -> None:
        """Reattach the existing view after login or an explicit owner start."""
        if self.reconnecting:
            return
        requested_cwd = str(self.agent.project_root_path.resolve())
        self.reconnecting = True
        try:
            try:
                selection = await asyncio.to_thread(
                    RouteSelection.for_child, os.environ.copy(), requested_cwd)
                await AcpIngress(selection, Path(requested_cwd),
                                 self.agent.process.attached_root(self.agent)).preflight()
            except (RouteChanged, RelationViolationError) as error:
                self.startup_failed(f"Reconnect blocked before restart: {error}")
                return
            await self.agent.stop()
            self.load_plan = plan or EnsuringSessionLoadPlan()
            self.settled.clear()
            await self.agent.start((self.agent.process,))
            try:
                await asyncio.wait_for(
                    self.settled.wait(), timeout=self.reconnect_timeout_seconds)
            except TimeoutError:
                self.startup_failed(
                    f"Reconnect timed out after {self.reconnect_timeout_seconds} seconds "
                    "waiting for the session handshake to settle."
                )
        except (OSError, RequestError) as error:
            self.startup_failed(f"Reconnect failed: {type(error).__name__}: {error}")
        finally:
            self.reconnecting = False


    async def reconnect_after_login(self) -> None:
        """Only a session that is ready after its restart counts as a finished login."""
        await self.reconnect()
        if not self.ready:
            raise LoginNotReady(self.disposition.present("Session did not become ready after login", lambda status: status.notice))

    async def authenticate(self, method_id: str) -> None:
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        authority.require()
        await self.agent.process.rpc.authenticate(method_id)
        authority.require()
        await self.initialize(force=True)
        authority.require()


    async def initialize(self, *, force=False):
        """The connection owns its original initialization response."""
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        authority.require()
        response = self.agent.process.initialization
        if response is None or force:
            response = await self.agent.process.rpc.initialize(
                PROTOCOL_VERSION,
                schema.ClientCapabilities(fs=schema.FileSystemCapabilities(
                    read_text_file=True, write_text_file=True), terminal=True,
                    auth=schema.AuthCapabilities(terminal=os.name != "nt")),
                schema.Implementation(name=toad.NAME, title=toad.TITLE, version=toad.get_version()),
            )
            authority.require()
            assert response is not None
            self.agent.process.initialization = response
        authority.require()


    async def new(self) -> None:
        """Create a new session."""
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        authority.require()
        cursor_token = self.agent._private_cursor.begin(None)
        queue_token = self.agent.queue_attachment.begin(None)
        self.agent._post_private_cursor()
        self.agent._post_queue_view()
        response = await self.agent.process.rpc.new_session(
            str(self.agent.project_root_path), mcp_servers=[])
        authority.require()
        if not self.agent._private_cursor.is_current_request(cursor_token):
            return
        assert response is not None
        self.agent.session_id = response.session_id
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        await self.agent.comms_consumer_class(
            self.agent, self.agent.session_id,
            cursor_token=cursor_token, queue_token=queue_token,
        ).consume_metadata(response.field_meta)

        if self.supports_load:
            db = DB()
            session_name = (
                self.chosen_name
                if self.chosen_name is not None
                else (self.agent.coordination.title if self.agent.coordination else "New Session")
            )
            session_pk = await db.session_new(
                session_name,
                self.agent.definition.name,
                self.agent.definition.identity,
                self.agent.session_id,
                protocol="acp",
                meta=SessionMeta(
                    cwd=self.agent.project_root_path, agent_data=self.agent.definition
                ),
            )
            authority.require()
            if not self.agent._private_cursor.is_current_request(cursor_token):
                return
            self.pk = session_pk
            authority.require()

        if not self.agent._private_cursor.is_current_request(cursor_token):
            return
        self.publish_configuration(response)


    async def load(self) -> None:
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        authority.require()
        assert self.agent.controller.session.bound, "Session id must be set"
        request_session_id = self.agent.session_id
        cursor_token = self.agent._private_cursor.begin(request_session_id)
        queue_token = self.agent.queue_attachment.begin(request_session_id)
        self.agent._post_private_cursor()
        self.agent._post_queue_view()
        cwd = str(self.agent.project_root_path)
        if self.pk is not None:
            db = DB()
            session = await db.session_get(self.pk)
            authority.require()
            if not self.agent._private_cursor.is_current_request(cursor_token):
                return
            if session is not None:
                if session_cwd := session.meta_json.cwd:
                    cwd = str(session_cwd)
                if agent_data := session.meta_json.agent_data:
                    self.agent.definition = agent_data

        plan, self.load_plan = self.load_plan, EnsuringSessionLoadPlan()
        try:
            response = await self.agent.process.rpc.load_session(
                cwd, request_session_id, mcp_servers=[], **(plan.metadata() or {}))
        except RequestError as error:
            authority.require()
            if self.agent.queue_attachment.is_current_request(queue_token):
                if failed_command := FailedSessionLoadPlan.from_failure(error.data):
                    self.load_plan = failed_command
            raise
        authority.require()
        if (
            not self.agent._private_cursor.is_current_request(cursor_token)
            or self.agent.session_id != request_session_id
        ):
            return
        assert response is not None
        owner = IncompatibleOwner.from_failure(response.field_meta)
        if owner is not None:
            self.agent.queue_attachment.unavailable = HistoryOnlyQueueProjection(owner)
        await self.agent.comms_consumer_class(
            self.agent, self.agent.session_id,
            cursor_token=cursor_token, queue_token=queue_token,
        ).consume_metadata(response.field_meta)
        if owner is not None:
            self.disposition = HistoryOnlySessionDisposition(self, owner)

        self.publish_configuration(response)


    async def rename_coordination(self, display_name: str) -> None:
        if not self.accepts_session(self.agent.session_id):
            return
        thread = self.agent.coordination.thread.name if self.agent.coordination else None
        wire_root = self.agent.coordination.wire_root if self.agent.coordination else None
        if thread is None or wire_root is None:
            return

        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        owner_pid = self.agent.coordination.owner_pid
        async with self.agent.controller.transcripts.bind(wire_root) as comms:
            authority.require()
            result = await asyncio.to_thread(
                comms.threads.rename_managed_thread,
                thread, display_name, owner_pid=owner_pid,
            )
        authority.require()
        self.agent.coordination = replace(
            self.agent.coordination,
            thread=replace(self.agent.coordination.thread, name=result.current),
            title=display_name,
        )
        self.agent.events.publish(core_events.CommsUpdated(self.agent.coordination, self.agent.session_id))


    async def set_mode(self, mode_id: str) -> str | None:
        """Update the current mode with the agent."""
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        authority.require()
        try:
            await self.agent.process.rpc.set_session_mode(self.agent.session_id, mode_id)
            authority.require()
        except RequestError as error:
            return ACPFailure.from_error(error.code, error.message, error.data).feedback
        else:
            self.agent.controller.update_mode(mode_id)
            return None


    async def set_name(self, name: str) -> None:
        """The user or agent process named this session.

        The name sticks: no later presented title replaces it. Naming it
        again with the name it already carries does nothing.
        """
        if self.chosen_name == name:
            return
        self.chosen_name = name or None
        await self.rename_coordination(name)
        if self.pk is None:
            return
        db = DB()
        await db.session_update_title(self.pk, name)


    def publish_configuration(self, response):
        self.load_plan = SessionLoadPlan.at_response(response.field_meta)
        if (modes := response.modes) is not None:
            self.agent.controller.publish_modes(modes)
        self.agent.configuration.receive(response.config_options)
