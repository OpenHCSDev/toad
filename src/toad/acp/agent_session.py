"""ACP session handshake, durable metadata and reconnection."""
from __future__ import annotations

from agent_comms.repo import Checkout

import asyncio
import os
from collections.abc import Coroutine
from dataclasses import replace
from functools import partial

from acp import ClientSideConnection, schema
from acp.exceptions import RequestError
from agent_comms.acp_extension import HistoryOnlyQueueProjection
from agent_comms.acp_failure import ACPFailure, RequestFailure
from toad.resource_retirement import RetiresResources
from agent_comms.errors import RouteChangedError
from agent_comms.input_attempt import NotSentInput
from agent_comms.owner_protocol import IncompatibleOwner
from agent_comms.session_load import (
    EnsuringSessionLoadPlan,
    SessionLoadPlan,
)

import toad
from toad import constants
from toad.acp.client_session import ClientSessionRequest
from toad.acp.initialization import InitializedAgent
from toad.acp.session_identity import SessionIdentity
from toad.acp.session_disposition import (
    ActiveSessionDisposition,
    FailedSessionDisposition,
    HistoryOnlySessionDisposition,
    RefusedSessionDisposition,
    SessionDisposition,
    SessionLifetime,
)
from toad.core import events as core_events
from toad.core.events import (
    AgentFail,
    AgentReady,
    LogAgentFail,
    UnsupportedResumeAgentFail,
)
from toad.db import DB, SessionMeta

from toad.acp import session_agent

PROTOCOL_VERSION = 1


class LoginNotReady(ValueError):
    """A terminal login finished, but the session it restarted did not become ready."""


class AgentSession(RetiresResources, SessionLifetime):
    """Own readiness and durable session effects; binding identity stays on the controller."""

    reconnect_timeout_seconds = 30

    def __init__(self, agent: session_agent.SessionAgent, pk, app_events: core_events.CoreEventStream) -> None:
        self.agent = agent
        # The app's stream: its thread rows show this session's state, attached to a view or not.
        self.app_events = app_events
        self.task: asyncio.Task[None] | None = None
        self.responses: set[asyncio.Task[object]] = set()
        self._disposition: SessionDisposition = ActiveSessionDisposition(self)
        self.pk = pk
        self.chosen_name: str | None = None
        self.connected = False
        self.reconnecting = False
        self.load_plan: SessionLoadPlan = EnsuringSessionLoadPlan()
        self.settled = asyncio.Event()

    def publish_thread_row_state(self) -> None:
        self.agent.coordination_attachment.publish_row_state(self.app_events)

    @property
    def disposition(self) -> SessionDisposition:
        return self._disposition

    @disposition.setter
    def disposition(self, state: SessionDisposition) -> None:
        if state is not self._disposition:
            self._disposition = state
            self.publish_thread_row_state()

    @property
    def capabilities(self):
        return self.agent.process.initialization.capabilities

    def accepts_session(self, session_id: str) -> bool:
        """Only this active session may consume foreign SDK work for its binding."""
        return self.accepts_updates and self.agent.controller.session.session_id == session_id

    def accepts_identity(self, expected: SessionIdentity) -> bool:
        """Retain the supplied expected key, including a mismatched or unbound key."""
        return self.accepts_updates and expected.matches(self.agent.controller.session)

    def _track_operation[Result](self, operation: Coroutine[None, None, Result]) -> asyncio.Task[Result]:
        task = asyncio.create_task(operation)
        self.responses.add(task)
        task.add_done_callback(self.responses.discard)
        return task

    def start_operation[Result](self, operation: Coroutine[None, None, Result]) -> asyncio.Task[Result]:
        task = self._track_operation(operation)
        if not self.accepts_updates:
            task.cancel()
        return task

    def cancel_responses(self) -> None:
        """Transport retirement cancels session work through its actual owner."""
        for task in tuple(self.responses):
            task.cancel()

    async def close_in(self, connection: ClientSideConnection) -> None:
        """Closing the remote session is tracked even after input stops."""
        await self._track_operation(connection.close_session(self.agent.controller.session.session_id))

    def close(self) -> None:
        self.disposition = self.disposition.close(self.agent.controller)

    def reopen(self) -> None:
        self.disposition = ActiveSessionDisposition(self)
        self.reset_retirement()

    def start(self) -> None:
        self.task = asyncio.create_task(self.run())
        self.task.add_done_callback(self.session_finished)

    def retirement_started(self, task: asyncio.Task[None]) -> None:
        task.add_done_callback(self.retirement_finished)

    async def _retire(self) -> None:
        pending = tuple(task for task in (self.task, *self.responses)
                        if task is not None)
        if self.task is not None:
            self.task.cancel()
        self.cancel_responses()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.responses.clear()
        self.task = None
        await self.agent.process.detach(self)

    def session_finished(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None and self.accepts_updates:
            self.startup_failed(f"{type(error).__name__}: {error}")

    def retirement_finished(self, task: asyncio.Task[None]) -> None:
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

    def session_failed(self, failure: ACPFailure) -> None:
        self.record_failure(
            LogAgentFail(failure.title, failure.feedback, log_path=self.agent.presentation.log_path),
            RefusedSessionDisposition,
        )

    def startup_failed(self, details: str) -> None:
        self.record_failure(
            LogAgentFail("ACP session startup failed", description=details,
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

    def starting(self) -> None:
        """Starting clears readiness before any asynchronous work."""
        self.connected = False
        self.settled.clear()
        self.agent.controller.reset_configuration()

    def closed(self) -> None:
        self.connected = False

    async def touch(self) -> None:
        if self.pk is not None:
            await DB().session_update_last_used(self.pk)

    def coordinated_title(self, title) -> None:
        """A coordination update presents the thread's title.

        A name the user chose wins: it is announced as the session's title
        and carried to the wire when the wire does not already carry it.
        Otherwise the saved title and the tab follow the thread's title.
        """
        from toad.core.events import SessionInfoUpdate, SessionThreadTitle
        self.agent.events.publish(SessionInfoUpdate(self.chosen_name or title))
        if self.chosen_name is not None:
            self.agent.coordination_attachment.rename_if_different(self.agent, self.chosen_name)
            return
        if title:
            self.agent.events.publish(SessionThreadTitle(title))
            if self.pk is not None:
                self.start_operation(self._adopt_thread_title(title))

    async def _adopt_thread_title(self, title) -> None:
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
                failure = replace(RequestFailure.from_error(error).failure,
                                  input_state=NotSentInput)
                self.session_failed(failure)
                return
        self.settled.set()
        self.publish_thread_row_state()
        self.agent.events.publish(AgentReady(session_id=self.agent.controller.session.session_id, reconnected=self.reconnecting))


    async def reconnect(self, plan: SessionLoadPlan | None = None) -> None:
        """Reattach the existing view after login or an explicit owner start."""
        if self.reconnecting:
            return
        self.reconnecting = True
        try:
            try:
                await asyncio.to_thread(
                    lambda: self.agent.controller.transcripts.access.selection)
            except RouteChangedError as error:
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
        except RequestError as error:
            self.startup_failed(f"Reconnect failed: {type(error).__name__}: {error}")
        finally:
            self.reconnecting = False


    async def reconnect_after_login(self) -> None:
        """Only a session that is ready after its restart counts as a finished login."""
        await self.reconnect()
        if not self.ready:
            raise LoginNotReady(self.disposition.refusal_notice)

    async def authenticate(self, method_id: str) -> None:
        authority = ClientSessionRequest(self.agent, self.agent.controller.session)
        authority.require()
        await self.agent.process.rpc.authenticate(method_id)
        authority.require()
        await self._initialize(authority)
        authority.require()


    async def initialize(self) -> None:
        """The connection owns its original initialization response."""
        authority = ClientSessionRequest(self.agent, self.agent.controller.session)
        authority.require()
        await self.agent.process.initialization.initialize(
            partial(self._initialize, authority),
        )
        authority.require()

    async def _initialize(self, authority: ClientSessionRequest) -> None:
        response = await self.agent.process.rpc.initialize(
            PROTOCOL_VERSION,
            schema.ClientCapabilities(fs=schema.FileSystemCapabilities(
                read_text_file=True, write_text_file=True), terminal=True,
                auth=schema.AuthCapabilities(terminal=os.name != "nt")),
            schema.Implementation(name=toad.NAME, title=toad.TITLE, version=toad.get_version()),
        )
        authority.require()
        assert response is not None
        self.agent.process.initialization = InitializedAgent(response)


    async def new(self) -> None:
        """Create a new session."""
        authority = ClientSessionRequest(self.agent, self.agent.controller.session)
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
        self.agent.controller.bind_session(response.session_id)
        bound_session_id = self.agent.controller.session.require_session_id()
        authority = ClientSessionRequest(self.agent, self.agent.controller.session)
        await self.agent.comms_consumer_class(
            self.agent, bound_session_id,
            cursor_token=cursor_token, queue_token=queue_token,
        ).consume_metadata(response.field_meta)

        if self.pk is not None:
            await DB().session_started(self.pk, response.session_id)
            authority.require()
        elif self.supports_load:
            db = DB()
            session_name = (
                self.chosen_name
                if self.chosen_name is not None
                else self.agent.coordination_attachment.title
            )
            session_pk = await db.session_new(
                session_name,
                self.agent.definition.name,
                self.agent.definition.identity,
                response.session_id,
                protocol="acp",
                meta=SessionMeta(
                    cwd=Checkout(self.agent.project_root_path), agent_data=self.agent.definition
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
        authority = ClientSessionRequest(self.agent, self.agent.controller.session)
        authority.require()
        request_session_id = authority.binding.require_session_id()
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
                for session_cwd in session.meta_json.cwd.present():
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
                self.load_plan = SessionLoadPlan.from_failure(error.data)
            raise
        authority.require()
        if (
            not self.agent._private_cursor.is_current_request(cursor_token)
            or not self.agent.controller.session.accepts_notification(request_session_id)
        ):
            return
        assert response is not None
        owner = IncompatibleOwner.from_failure(response.field_meta)
        if owner is not None:
            self.agent.queue_attachment.unavailable = HistoryOnlyQueueProjection(owner)
        await self.agent.comms_consumer_class(
            self.agent, request_session_id,
            cursor_token=cursor_token, queue_token=queue_token,
        ).consume_metadata(response.field_meta)
        if owner is not None:
            self.disposition = HistoryOnlySessionDisposition(self, owner)

        self.publish_configuration(response)


    async def set_name(self, name: str) -> None:
        """The user or agent process named this session.

        The name sticks: no later presented title replaces it. Naming it
        again with the name it already carries does nothing.
        """
        if self.chosen_name == name:
            return
        self.chosen_name = name or None
        await self.agent.coordination_attachment.rename(self.agent, name)
        if self.pk is None:
            return
        db = DB()
        await db.session_update_title(self.pk, name)


    def publish_configuration(self, response) -> None:
        self.load_plan = SessionLoadPlan.at_response(response.field_meta)
        self.agent.configuration.receive(response.config_options)
