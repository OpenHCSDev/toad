"""Owner operations inherited by the operational ACP agent."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import cache, partial
from dataclasses import replace
from pathlib import Path
from pydantic import JsonValue

from agent_comms.acp_extension import CoordinationChangedUpdate, GoalSnapshotReply, PromptRequest, QueueScope
from agent_comms.planning.goal_actions import GoalAction
from agent_comms.planning.goal_history import RecordedGoalHistory
from agent_comms.planning.goal_presentation import GoalSnapshot
from agent_comms.planning.goals import (
    Goal,
    GoalDeclaration,
)
from agent_comms.transport.tools.reads import InputDeliveryRead
from agent_comms.planning.goal_scope import OneGoal
from agent_comms.projects.checkouts import Checkout
from agent_comms.runtime_server import AttachedRuntimeRequest
from agent_comms.runtime_requests import (
    DismissHistoricalInputsRuntimeRequest, EditGoalRuntimeRequest, GoalHistoryRuntimeRequest,
)
from agent_comms.transport.tools.sidebar import (
    CommsCaptureHumanInputTool, CommsMoveThreadProjectTool,
    CommsOwnerRequestTool, CommsRenameManagedThreadTool,
)
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.session_load import ExistingSessionLoadPlan
from agent_comms.sent_message import AssignedSourceIdentity
from agent_comms.nominal.field_codec import FieldCodec, GoalId
from agent_comms.ui_model.delivery import DeliveryView, ReadDeliveryView
from agent_comms.ui_model.observation import ReadOwnerOperation
from toad.agent import AgentBase
from toad.core import events as core_events
from .agent_controller import AgentController, SourceIdentity
from .client_session import ClientSessionRequest, OwnerRequest
from agent_comms.nominal.field_codec import AcpSessionId


class SessionAgent(AgentBase, SourceIdentity):
    """Operational resources stay on the same agent through SDK source selection."""

    controller: AgentController
    supports_queue = False

    @property
    def source_title(self) -> str:
        return "New Session"

    @property
    def tool_scope(self) -> AssignedSourceIdentity | None:
        return None

    def publish_coordination(self, session_id: AcpSessionId) -> None:
        """No coordinator source belongs to the uncoordinated session."""

    def publish_thread_row_state(self) -> None:
        """No native thread row belongs to the uncoordinated session."""

    def rename_chosen_title(self, title: str) -> None:
        """No native thread title belongs to the uncoordinated session."""

    async def prepare_login(self, prepare: Callable[[], Awaitable[None]]) -> None:
        await prepare()

    @property
    def coordination(self) -> CoordinationChangedUpdate | None:
        return None

    @classmethod
    @cache
    def _coordinated_type(cls) -> type[SessionAgent]:
        return type(f"Coordinated{cls.__name__}", (cls, CoordinatedSessionAgent),
                    {"__module__": cls.__module__})

    def receive_coordination(self, update: CoordinationChangedUpdate) -> None:
        self._coordination = update
        self.__class__ = self._coordinated_type()

    async def request_owner(self, captured: OwnerRequest, operation: AttachedRuntimeRequest) -> JsonValue:
        raise ValueError("This action requires an agent-comms thread.")

    def capture_owner_request(self, authority: ClientSessionRequest) -> OwnerRequest:
        raise ValueError("The connected owner session retired; refresh its state.")

    async def input_delivery(self, *, include_history: bool = False) -> DeliveryView:
        return DeliveryView()

    @property
    def supports_images(self) -> bool:
        return self.session.supports_images

    async def prepare_command(self, command: PromptRequest, authority: ClientSessionRequest, scope: QueueScope) -> PromptRequest:
        return command

    def prompt_settlement(self, authority: ClientSessionRequest) -> Callable[[], None]:
        return self._no_prompt_settlement

    def _no_prompt_settlement(self) -> None:
        """No coordinator source was captured when this prompt started."""

    async def update_project(self, path: str) -> str:
        raise ValueError("Project changes require an agent-comms thread.")

    async def rename_coordination(self, display_name: str) -> None:
        """An uncoordinated session has no native thread to rename."""

    async def dismiss_historical_inputs(self):
        request = self.capture_owner_request(ClientSessionRequest(self, self.session_id))
        return await self.request_owner(request, DismissHistoricalInputsRuntimeRequest(
            thread=request.coordination.thread.name,
        ))

    async def get_goal_snapshot(self) -> GoalSnapshot:
        return await self.thread_read().goal_snapshot(self.controller.transcripts)

    async def get_goal_history(self, goal_id: GoalId) -> RecordedGoalHistory:
        request = self.capture_owner_request(ClientSessionRequest(self, self.session_id))
        result = await self.request_owner(request, GoalHistoryRuntimeRequest(
            thread=request.coordination.thread.name, goal_id=OneGoal(goal_id),
        ))
        return FieldCodec.decode(RecordedGoalHistory, result)

    async def edit_goal(self, goal: Goal, text: str) -> Goal:
        request = self.capture_owner_request(ClientSessionRequest(self, self.session_id))
        result = await self.request_owner(request, EditGoalRuntimeRequest(
            thread=request.coordination.thread.name, goal_id=goal.id,
            expected_revision=goal.revision, text=text,
        ))
        return FieldCodec.decode(GoalSnapshotReply, result).goal.require()

    async def update_goal(self, action: type[GoalAction], text: str = "") -> GoalDeclaration:
        request = self.capture_owner_request(ClientSessionRequest(self, self.session_id))
        request.require()
        result = await action.submit_control(
            request.coordination.thread,
            partial(self.owner_read(request).goal_snapshot, self.controller.transcripts),
            partial(self.request_owner, request), text,
        )
        request.require()
        return result


class CoordinationIdentity(SessionAgent):
    """An accepted SDK update supplies the original root and thread incarnation."""

    supports_queue = True
    automatic_titles = False

    @property
    def source_title(self) -> str:
        return self.coordination.title

    @property
    def tool_scope(self) -> AssignedSourceIdentity | None:
        coordination = self.coordination
        return coordination.thread.recorded_or(
            lambda recorded: AssignedSourceIdentity(coordination.wire_root, recorded), lambda: None)

    def publish_coordination(self, session_id: AcpSessionId) -> None:
        self.events.publish(core_events.CommsUpdated(self.coordination, session_id))

    def publish_thread_row_state(self) -> None:
        self.session.app_events.publish(core_events.ThreadRowStateChanged(
            frozenset((self.coordination.thread.name,))))

    def rename_chosen_title(self, title: str) -> None:
        if self.coordination.title != title:
            self.session.start_operation(self.rename_coordination(title))

    async def prepare_login(self, prepare: Callable[[], Awaitable[None]]) -> None:
        """A native source keeps its history across provider login."""

    @property
    def coordination(self) -> CoordinationChangedUpdate:
        return self._coordination

    @classmethod
    def _coordinated_type(cls) -> type[SessionAgent]:
        return cls

    def observed_thread(self) -> tuple[str, str]:
        return self.coordination.wire_root, self.coordination.thread.name

    def matches_source(self, root: str, thread: ThreadIncarnation) -> bool:
        return (self.coordination.wire_root, self.coordination.thread) == (root, thread)

    def capture_owner_request(self, authority: ClientSessionRequest) -> OwnerRequest:
        return OwnerRequest(self.coordination, authority)


class OwnerRequests(CoordinationIdentity):
    async def request_owner(self, captured: OwnerRequest, operation: AttachedRuntimeRequest) -> JsonValue:
        captured.require()
        coordination = captured.coordination
        core = await self.controller.transcripts.core(coordination.wire_root)
        captured.require()
        result = await asyncio.to_thread(core.call, CommsOwnerRequestTool(
            owner=coordination.thread, request=operation,
        ))
        captured.require()
        return result.payload


class OwnerReads(CoordinationIdentity):
    async def observe_thread_presentation(self, presentation: ThreadPresentation) -> None:
        session = self.session
        if not session.settled.is_set() or session.reconnecting:
            return
        binding = presentation.binding
        if not session.load_plan.superseded_by(binding):
            return
        await session.reconnect(ExistingSessionLoadPlan(binding))

    def owner_read(self, request: OwnerRequest):
        from .comms_updates import PendingThreadRead
        return PendingThreadRead(request, turn_token=self.presentation.turns.sequence)

    def thread_read(self):
        return self.owner_read(self.capture_owner_request(ClientSessionRequest(self, self.session_id)))

    async def input_delivery(self, *, include_history: bool = False) -> DeliveryView:
        request = self.capture_owner_request(ClientSessionRequest(self, self.session_id))
        coordination = request.coordination
        overview = await self.controller.transcripts.read(ReadOwnerOperation(
            coordination.wire_root, coordination.thread, InputDeliveryRead(include_history=include_history),
        ))
        request.require()
        return ReadDeliveryView(overview)


class OwnerPrompts(CoordinationIdentity):
    supports_images = True

    async def prepare_command(self, command: PromptRequest, authority: ClientSessionRequest, scope: QueueScope) -> PromptRequest:
        request = self.capture_owner_request(authority)
        request.require()
        core = await self.controller.transcripts.core(request.coordination.wire_root)
        request.require()
        claimed_identity = self.queue_attachment.input_identity(scope)
        origin = await asyncio.to_thread(core.call, CommsCaptureHumanInputTool(
            claimed_identity=claimed_identity,
        ))
        request.require()
        self.queue_attachment.input_identity(scope)
        return replace(command, origin=origin)

    def prompt_settlement(self, authority: ClientSessionRequest) -> Callable[[], None]:
        request = self.capture_owner_request(authority)

        def settle() -> None:
            self.controller.start_operation(self.reconcile_turn(request))

        return settle

    async def reconcile_turn(self, request: OwnerRequest) -> None:
        request.require()
        await self.owner_read(request).reconcile(self.controller.transcripts)


class OwnerWrites(CoordinationIdentity):
    async def update_project(self, path: str) -> str:
        request = self.capture_owner_request(ClientSessionRequest(self, self.session_id))
        coordination = request.coordination
        request.require()
        core = await self.controller.transcripts.core(coordination.wire_root)
        request.require()
        result = await asyncio.to_thread(core.call, CommsMoveThreadProjectTool(
            owner=coordination.thread, path=path,
        ))
        request.require()
        worktree = Checkout(Path(result.current))
        self.receive_coordination(replace(self.coordination, worktree=worktree))
        self.project_root_path = worktree.path
        self.events.publish(core_events.CommsUpdated(self.coordination, self.session_id))
        return result.current

    async def rename_coordination(self, display_name: str) -> None:
        if not self.session.accepts_session(self.session_id):
            return
        request = self.capture_owner_request(ClientSessionRequest(self, self.session_id))
        coordination = request.coordination
        request.require()
        core = await self.controller.transcripts.core(coordination.wire_root)
        request.require()
        result = await asyncio.to_thread(core.call, CommsRenameManagedThreadTool(
            thread=coordination.thread, display_name=display_name, owner=coordination.owner,
        ))
        request.require()
        self.receive_coordination(replace(
            self.coordination, thread=replace(self.coordination.thread, name=result.current),
            title=display_name))
        self.events.publish(core_events.CommsUpdated(self.coordination, self.session_id))


class CoordinatedSessionAgent(OwnerRequests, OwnerReads, OwnerWrites, OwnerPrompts):
    """The SDK-selected agent composes requests, captured reads and owner writes."""
