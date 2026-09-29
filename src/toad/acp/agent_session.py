"""ACP session handshake, durable metadata and reconnection custody."""
from __future__ import annotations
import asyncio
import os
from typing import NamedTuple
from dataclasses import replace
import toad
from toad import constants, jsonrpc
from toad.acp import api, messages
from acp import schema
from toad.acp.client_session import ClientSessionRequest
from toad.agent import AgentReady, UnsupportedResumeAgentFail
from toad.db import DB, SessionMeta
from agent_comms.acp_failure import ACPFailure
from agent_comms.input_attempt import NotSentInput

PROTOCOL_VERSION = 1


class Mode(NamedTuple):
    """An agent mode."""

    id: str
    name: str
    description: str | None



class AgentSession:
    """Own readiness and durable session effects; binding identity stays on the controller."""
    def __init__(self, agent, pk):
        self.agent = agent
        self.pk = pk
        self.pending_name = None
        self.connected = False
        self.reconnecting = False
        self.settled = asyncio.Event()
        self.capabilities = schema.AgentCapabilities()

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
        """Start admission clears readiness before any asynchronous work."""
        self.connected = False
        self.settled.clear()

    def closed(self):
        self.connected = False

    def failed(self):
        self.closed()
        self.settled.set()

    async def touch(self):
        if self.pk is not None:
            await DB().session_update_last_used(self.pk)

    def coordinated_title(self, title):
        self.agent.post_message(messages.SessionInfoUpdate(self.pending_name or title))
        if self.pending_name is not None:
            self.rename_coordination(self.pending_name)
            self.pending_name = None

    async def run(self) -> None:
        """The main logic of the Agent."""
        if constants.ACP_INITIALIZE:
            self.connected = False
            try:
                await self.initialize()
                if self.agent.controller.session.bound:
                    if not self.supports_load:
                        self.agent.post_message(
                            UnsupportedResumeAgentFail(
                                "Resume not supported",
                                f"{self.agent.definition.name} does not currently support resuming sessions.",
                            )
                        )
                        self.settled.set()
                        return
                    await self.load()
                    await self.touch()
                else:
                    await self.new()
                self.connected = True
            except jsonrpc.APIError as error:
                # The handshake has not admitted a prompt, regardless of the
                # server's reason for refusing this attachment.
                failure = replace(ACPFailure.from_error(error.code, error.message, error.data),
                                  input_state=NotSentInput)
                self.agent.process.session_failed(failure)
                return
        self.settled.set()
        self.agent.post_message(AgentReady(reconnected=self.reconnecting))


    async def reconnect(self) -> None:
        """Reattach the existing view after login or an explicit owner start."""
        if self.agent.controller.session.bound and not self.supports_load:
            raise ValueError("This agent cannot resume its session.")
        from .maintenance_ingress import configured_root, preflight

        requested_env = os.environ.copy()
        requested_cwd = str(self.agent.project_root_path.resolve())
        requested_root = configured_root(requested_env, requested_cwd)
        try:
            await asyncio.to_thread(
                preflight,
                (self.agent.coordination.wire_root if self.agent.coordination else None),
                ingress_root=requested_root,
                cwd=requested_cwd,
            )
        except Exception as error:
            raise ValueError(
                f"Reconnect not attempted: maintenance admission denied: {error}"
            ) from error
        target = self.agent.controller.surface.target
        await self.agent.stop()
        self.reconnecting = True
        self.settled.clear()
        try:
            await self.agent.start(target)
            await asyncio.wait_for(self.settled.wait(), timeout=30)
            if not self.connected:
                raise ValueError("The agent could not reconnect.")
        finally:
            self.reconnecting = False


    async def authenticate(self, method_id: str) -> None:
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        authority.require()
        with self.agent.request():
            response = api.authenticate(method_id)
        await response.wait()
        authority.require()
        await self.initialize()
        authority.require()


    async def initialize(self):
        """Initialize agent."""
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        authority.require()
        with self.agent.request():
            initialize_response = api.initialize(
                PROTOCOL_VERSION,
                schema.ClientCapabilities(fs=schema.FileSystemCapabilities(
                    read_text_file=True, write_text_file=True), terminal=True,
                    auth=schema.AuthCapabilities(terminal=os.name != "nt")),
                schema.Implementation(name=toad.NAME, title=toad.TITLE, version=toad.get_version()),
            )

        response = await initialize_response.wait()
        authority.require()
        assert response is not None

        # Store agents capabilities
        if agent_capabilities := response.agent_capabilities:
            self.capabilities = agent_capabilities
        self.agent.presentation.auth_methods = response.auth_methods or []


    async def new(self) -> None:
        """Create a new session."""
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        authority.require()
        cursor_token = self.agent._private_cursor.begin(None)
        queue_token = self.agent.queue_attachment.begin(None)
        self.agent._post_private_cursor()
        self.agent._post_queue_view()
        with self.agent.request():
            session_new_response = api.session_new(
                str(self.agent.project_root_path),
                [],
            )
        response = await session_new_response.wait()
        authority.require()
        if not self.agent._private_cursor.is_current_request(cursor_token):
            return
        assert response is not None
        self.agent.session_id = response.session_id
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        self.agent._receive_comms_metadata(response.field_meta, cursor_token, queue_token)

        if self.supports_load:
            db = DB()
            session_name = (
                self.pending_name
                if self.pending_name is not None
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
            if self.pk is not None and self.pending_name is not None:
                await db.session_update_title(
                    self.pk, self.pending_name
                )
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

        with self.agent.request():
            session_load_response = api.session_load(cwd, [], request_session_id)
        response = await session_load_response.wait()
        authority.require()
        if (
            not self.agent._private_cursor.is_current_request(cursor_token)
            or self.agent.session_id != request_session_id
        ):
            return
        assert response is not None
        self.agent._receive_comms_metadata(response.field_meta, cursor_token, queue_token)

        self.publish_configuration(response)


    def rename_coordination(self, display_name: str) -> None:
        if not self.agent.process.accepts_session(self.agent.session_id):
            return
        thread = self.agent.coordination.thread.name if self.agent.coordination else None
        wire_root = self.agent.coordination.wire_root if self.agent.coordination else None
        if thread is None or wire_root is None:
            return

        from agent_comms.comms import wire

        result = wire(wire_root).threads.rename_managed_thread(
            thread,
            display_name,
            owner_pid=self.agent.coordination.owner_pid,
        )
        self.agent.coordination = replace(
            self.agent.coordination,
            thread=replace(self.agent.coordination.thread, name=result.current),
            title=display_name,
        )
        self.agent.post_message(
            messages.CommsUpdated(self.agent.coordination, self.agent, self.agent.session_id)
        )


    async def set_mode(self, mode_id: str) -> str | None:
        """Update the current mode with the agent."""
        authority = ClientSessionRequest(self.agent, self.agent.session_id)
        authority.require()
        with self.agent.request():
            response = api.session_set_mode(self.agent.session_id, mode_id)
        try:
            await response.wait()
            authority.require()
        except jsonrpc.APIError as error:
            return ACPFailure.from_error(error.code, error.message, error.data).feedback
        else:
            return None


    async def set_name(self, name: str) -> None:
        self.pending_name = name
        self.rename_coordination(name)
        if (self.agent.coordination.thread.name if self.agent.coordination else None) is not None:
            self.pending_name = None
        if self.pk is None:
            return
        db = DB()
        await db.session_update_title(self.pk, name)


    def publish_configuration(self, response):
        if (modes := response.modes) is not None:
            self.agent.controller.publish_modes(modes.current_mode_id, {
                mode.id: Mode(mode.id, mode.name, mode.description)
                for mode in modes.available_modes})
        self.agent.configuration.receive(response.config_options)
