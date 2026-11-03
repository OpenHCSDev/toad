"""An agent's coordination attachment owns thread availability and source fencing."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path

from agent_comms.acp_extension import CoordinationChangedUpdate, PromptRequest, QueueScope
from agent_comms.goal_presentation import GoalSnapshot, IdleGoalExecution
from agent_comms.goals import NoGoal
from agent_comms.order_tools import InputDeliveryRead, OwnerGoalRead
from agent_comms.owner_connection import socket_path
from agent_comms.repo import Checkout
from agent_comms.runtime import RuntimeConnection
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.transcripts import TranscriptReadIdentity
from agent_comms.ui_model.delivery import DeliveryView, ReadDeliveryView
from agent_comms.ui_model.observation import ReadOwnerOperation
from pydantic import JsonValue

from toad.acp.client_session import ClientSessionRequest
from toad.acp.agent_controller import SessionBinding
from toad.acp.comms_updates import OwnerSnapshotConsumer
from toad.acp.session_disposition import SessionLoginTarget
from toad.acp.thread_read import NoPendingThreadRead, PendingThreadRead, ThreadRead
from toad.acp.tool_source import AssignedToolCallSource, ToolCallSource, UncoordinatedToolCallSource
from toad.core.events import CoreEventStream, ThreadRowStateChanged

from toad.acp import session_agent


class CoordinationAttachment:
    """A genuine non-coordinated ACP session, not an optional packet."""

    queue_supported = False
    automatic_titles = True
    retired_notice = "The connected owner session retired; refresh its state."
    changed_notice = "The owner identity changed while preparing the request."

    @property
    def title(self) -> str:
        return "New Session"

    @property
    def tool_scope(self) -> ToolCallSource:
        return UncoordinatedToolCallSource()

    def matches_source(self, update: CoordinationChangedUpdate) -> bool:
        return False

    def matches_identity(self, root: str, thread: ThreadIncarnation) -> bool:
        return False

    def accepts_read(self, identity: TranscriptReadIdentity) -> bool:
        return False

    def require_current(self, agent: session_agent.SessionAgent, authority: ClientSessionRequest) -> None:
        raise ValueError(self.retired_notice)

    def require_source(self, update: CoordinationChangedUpdate, authority: ClientSessionRequest) -> None:
        raise ValueError(self.retired_notice)

    def publish(self, agent: session_agent.SessionAgent, binding: SessionBinding) -> None:
        """No coordination publication exists."""

    def publish_row_state(self, events: CoreEventStream) -> None:
        """No coordinated thread row changed."""

    def thread_read(self, agent: session_agent.SessionAgent) -> ThreadRead:
        return NoPendingThreadRead()

    def finish_prompt(self, agent: session_agent.SessionAgent, authority: ClientSessionRequest) -> None:
        """No coordinated turn needs a canonical read."""

    async def prepare_command(self, agent: session_agent.SessionAgent, command: PromptRequest,
                              authority: ClientSessionRequest, scope: QueueScope) -> PromptRequest:
        return command

    def require_input_source(self, agent: session_agent.SessionAgent, authority: ClientSessionRequest) -> None:
        if agent.coordination_attachment is not self:
            raise ValueError(self.changed_notice)

    def supports_images(self, agent: session_agent.SessionAgent) -> bool:
        return agent.session.supports_images

    async def request_owner(self, agent: session_agent.SessionAgent, method: str, **params: JsonValue):
        raise ValueError("This action requires an agent-comms thread.")

    async def input_delivery(self, agent: session_agent.SessionAgent, *, include_history: bool = False) -> DeliveryView:
        return DeliveryView()

    async def goal_snapshot(self, agent: session_agent.SessionAgent) -> GoalSnapshot:
        return GoalSnapshot(NoGoal(), IdleGoalExecution())

    async def update_project(self, agent: session_agent.SessionAgent, path: str) -> str:
        raise ValueError("Project changes require an agent-comms thread.")

    def apply_project(self, agent: session_agent.SessionAgent, project: Checkout) -> None:
        raise ValueError(self.retired_notice)

    async def rename(self, agent: session_agent.SessionAgent, name: str) -> None:
        """A non-coordinated session has no managed thread to rename."""

    def apply_name(self, agent: session_agent.SessionAgent, name: str, title: str) -> None:
        raise ValueError(self.retired_notice)

    def rename_if_different(self, agent: session_agent.SessionAgent, name: str) -> None:
        """No coordinated title needs synchronization."""

    async def observe_owner(self, agent: session_agent.SessionAgent, presentation: ThreadPresentation) -> None:
        """No coordinated process can supersede this attachment."""

    async def prepare_login(self, view: SessionLoginTarget) -> None:
        await view.prune_window(0, 0)
        view.output.boundary()


@dataclass(frozen=True)
class CoordinatedThread(CoordinationAttachment):
    """The original decoded publication; no second copy of its fields."""

    update: CoordinationChangedUpdate
    queue_supported = True
    automatic_titles = False

    @property
    def title(self) -> str:
        return self.update.title

    @property
    def tool_scope(self) -> ToolCallSource:
        return self.update.thread.recorded_or(
            lambda recorded: AssignedToolCallSource(self.update.wire_root, recorded),
            UncoordinatedToolCallSource,
        )

    def matches_source(self, update: CoordinationChangedUpdate) -> bool:
        return self.matches_identity(update.wire_root, update.thread)

    def matches_identity(self, root: str, thread: ThreadIncarnation) -> bool:
        return self.update.wire_root == root and self.update.thread == thread

    def accepts_read(self, identity: TranscriptReadIdentity) -> bool:
        return self.matches_identity(identity.root, identity.thread.incarnation)

    def require_current(self, agent: session_agent.SessionAgent, authority: ClientSessionRequest) -> None:
        agent.coordination_attachment.require_source(self.update, authority)

    def require_source(self, update: CoordinationChangedUpdate, authority: ClientSessionRequest) -> None:
        if authority.retired:
            raise ValueError(self.retired_notice)
        if not self.matches_source(update):
            raise ValueError(self.changed_notice)

    def publish(self, agent: session_agent.SessionAgent, binding: SessionBinding) -> None:
        agent.events.publish(binding.publication(self.update))

    def publish_row_state(self, events: CoreEventStream) -> None:
        events.publish(ThreadRowStateChanged(frozenset((self.update.thread.name,))))

    def thread_read(self, agent: session_agent.SessionAgent) -> ThreadRead:
        authority = ClientSessionRequest(agent, agent.controller.session)
        return PendingThreadRead(
            self, authority,
            OwnerSnapshotConsumer(agent, authority.binding.require_session_id(), turn_token=agent.presentation.turns.sequence),
        )

    def finish_prompt(self, agent: session_agent.SessionAgent, authority: ClientSessionRequest) -> None:
        agent.controller.start_operation(self.reconcile(agent, authority))

    async def reconcile(self, agent: session_agent.SessionAgent, authority: ClientSessionRequest) -> None:
        self.require_current(agent, authority)
        await agent.thread_read().reconcile(agent.controller.transcripts)

    async def prepare_command(self, agent: session_agent.SessionAgent, command: PromptRequest,
                              authority: ClientSessionRequest, scope: QueueScope) -> PromptRequest:
        self.require_current(agent, authority)
        comms = await agent.controller.transcripts.service(self.update.wire_root)
        self.require_current(agent, authority)
        origin = await asyncio.to_thread(agent.queue_attachment.capture_human_input, comms, scope)
        self.require_current(agent, authority)
        return replace(command, origin=origin)

    def require_input_source(self, agent: session_agent.SessionAgent, authority: ClientSessionRequest) -> None:
        self.require_current(agent, authority)

    def supports_images(self, agent: session_agent.SessionAgent) -> bool:
        return True

    async def request_owner(self, agent: session_agent.SessionAgent, method: str, **params: JsonValue):
        authority = ClientSessionRequest(agent, agent.controller.session)
        self.require_current(agent, authority)
        comms = await agent.controller.transcripts.service(self.update.wire_root)
        self.require_current(agent, authority)

        def resolve():
            owner = comms.registry.require(self.update.thread.name)
            if owner.incarnation != self.update.thread:
                raise ValueError("The owner incarnation changed while preparing the request.")
            return RuntimeConnection(
                comms, owner.incarnation, socket_path(comms.root, owner.require_process().pid)
            )

        proxy = await asyncio.to_thread(resolve)
        try:
            self.require_current(agent, authority)
            result = await proxy.request(method, **params)
            self.require_current(agent, authority)
            return result
        finally:
            await proxy.close()

    async def input_delivery(self, agent: session_agent.SessionAgent, *, include_history: bool = False) -> DeliveryView:
        authority = ClientSessionRequest(agent, agent.controller.session)
        overview = await agent.controller.transcripts.read(ReadOwnerOperation(
            self.update.wire_root, self.update.thread,
            InputDeliveryRead(include_history=include_history),
        ))
        self.require_current(agent, authority)
        return ReadDeliveryView(overview)

    async def goal_snapshot(self, agent: session_agent.SessionAgent) -> GoalSnapshot:
        authority = ClientSessionRequest(agent, agent.controller.session)
        consumer = OwnerSnapshotConsumer(agent, authority.binding.require_session_id(),
                                         turn_token=agent.presentation.turns.sequence)
        snapshot = await agent.controller.transcripts.read(ReadOwnerOperation(
            self.update.wire_root, self.update.thread, operation=OwnerGoalRead()))
        self.require_current(agent, authority)
        for fact in snapshot.meta.batch.updates:
            consumer.dispatch_sync(fact)
        return snapshot

    async def update_project(self, agent: session_agent.SessionAgent, path: str) -> str:
        authority = ClientSessionRequest(agent, agent.controller.session)
        self.require_current(agent, authority)
        comms = await agent.controller.transcripts.service(self.update.wire_root)
        self.require_current(agent, authority)
        result = await asyncio.to_thread(comms.threads.set_project, self.update.thread, path)
        self.require_current(agent, authority)
        agent.coordination_attachment.apply_project(agent, Checkout(Path(result.current)))
        return result.current

    def apply_project(self, agent: session_agent.SessionAgent, project: Checkout) -> None:
        agent.coordination_attachment = replace(self, update=replace(self.update, worktree=project))
        agent.project_root_path = project.path
        agent.coordination_attachment.publish(agent, agent.controller.session)

    async def rename(self, agent: session_agent.SessionAgent, name: str) -> None:
        if not agent.session.accepts_identity(agent.controller.session):
            return
        authority = ClientSessionRequest(agent, agent.controller.session)
        self.require_current(agent, authority)
        comms = await agent.controller.transcripts.service(self.update.wire_root)
        self.require_current(agent, authority)
        result = await asyncio.to_thread(
            comms.threads.rename_managed_thread, self.update.thread.name,
            name, owner=self.update.owner,
        )
        self.require_current(agent, authority)
        agent.coordination_attachment.apply_name(agent, result.current, name)
        agent.coordination_attachment.publish(agent, authority.binding)

    def apply_name(self, agent: session_agent.SessionAgent, name: str, title: str) -> None:
        agent.coordination_attachment = replace(self, update=replace(
            self.update, thread=replace(self.update.thread, name=name), title=title,
        ))

    def rename_if_different(self, agent: session_agent.SessionAgent, name: str) -> None:
        if self.update.title != name:
            agent.session.start_operation(self.rename(agent, name))

    async def observe_owner(self, agent: session_agent.SessionAgent, presentation: ThreadPresentation) -> None:
        session = agent.session
        if not session.settled.is_set() or session.reconnecting:
            return
        await presentation.binding.reload_if_superseded(session.load_plan, session.reconnect)

    async def prepare_login(self, view: SessionLoginTarget) -> None:
        """The coordinated source keeps its saved transcript during login."""
