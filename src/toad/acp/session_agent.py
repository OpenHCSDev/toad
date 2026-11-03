"""Owner operations inherited by the operational ACP agent."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import cache
from dataclasses import replace
from pathlib import Path
from pydantic import JsonValue

from agent_comms.acp_extension import CoordinationChangedUpdate, PromptRequest, QueueScope
from agent_comms.goal_actions import GoalAction
from agent_comms.goal_history import RecordedGoalHistory
from agent_comms.goal_presentation import GoalSnapshot
from agent_comms.goals import Goal, GoalDeclaration
from agent_comms.order_tools import InputDeliveryRead
from agent_comms.owner_connection import socket_path
from agent_comms.repo import Checkout
from agent_comms.runtime import RuntimeConnection
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.thread_presentation import ThreadPresentation
from agent_comms.session_load import ExistingSessionLoadPlan
from agent_comms.transcript_sources import AssignedSourceIdentity
from agent_comms.nominal.field_codec import FieldCodec, GoalId
from agent_comms.ui_model.delivery import DeliveryView, ReadDeliveryView
from agent_comms.ui_model.observation import ReadOwnerOperation
from toad.agent import AgentBase
from toad.core import events as core_events
from .agent_controller import AgentController, SourceIdentity
from .client_session import ClientSessionRequest


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

    def publish_coordination(self, session_id: str) -> None:
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

    async def request_owner(self, method: str, **params: JsonValue):
        raise ValueError("This action requires an agent-comms thread.")

    def require_owner(self, coordination: CoordinationChangedUpdate, authority: ClientSessionRequest):
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
        return await self.request_owner("dismiss_historical_inputs")

    async def get_goal_snapshot(self) -> GoalSnapshot:
        return await self.thread_read().goal_snapshot(self.controller.transcripts)

    async def get_goal_history(self, goal_id: GoalId) -> RecordedGoalHistory:
        result = await self.request_owner("goal_history", goal_id=goal_id)
        return FieldCodec.decode(RecordedGoalHistory, result)

    async def edit_goal(self, goal: Goal, text: str) -> Goal:
        result = await self.request_owner(
            "edit_goal", goal_id=goal.id, expected_revision=goal.revision, text=text
        )
        return FieldCodec.decode(Goal, result["goal"])

    async def update_goal(self, action: type[GoalAction], text: str = "") -> GoalDeclaration:
        result = await action.submit_control(self.get_goal_snapshot, self.request_owner, text)
        return FieldCodec.decode(GoalDeclaration, result["goal"])


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

    def publish_coordination(self, session_id: str) -> None:
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

    def require_owner(self, coordination: CoordinationChangedUpdate, authority: ClientSessionRequest):
        if authority.retired:
            raise ValueError("The connected owner session retired; refresh its state.")
        if not self.matches_source(coordination.wire_root, coordination.thread):
            raise ValueError("The owner identity changed while preparing the request.")


class OwnerRequests(CoordinationIdentity):
    async def request_owner(self, method: str, **params: JsonValue):
        coordination = self.coordination
        authority = ClientSessionRequest(self, self.session_id)
        self.require_owner(coordination, authority)
        comms = await self.controller.transcripts.service(coordination.wire_root)

        def resolve():
            owner = comms.registry.require(coordination.thread.name)
            if owner.incarnation != coordination.thread:
                raise ValueError("The owner incarnation changed while preparing the request.")
            return RuntimeConnection(
                comms, owner.incarnation, socket_path(comms.root, owner.require_process().pid)
            )

        proxy = await asyncio.to_thread(resolve)
        try:
            self.require_owner(coordination, authority)
            result = await proxy.request(method, **params)
            self.require_owner(coordination, authority)
            return result
        finally:
            await proxy.close()


class OwnerReads(CoordinationIdentity):
    async def observe_thread_presentation(self, presentation: ThreadPresentation) -> None:
        session = self.session
        if not session.settled.is_set() or session.reconnecting:
            return
        binding = presentation.binding
        if not session.load_plan.superseded_by(binding):
            return
        await session.reconnect(ExistingSessionLoadPlan(binding))

    def thread_read(self):
        from .comms_updates import OwnerSnapshotConsumer, PendingThreadRead
        coordination = self.coordination
        return PendingThreadRead(self, coordination, ClientSessionRequest(self, self.session_id),
                                 OwnerSnapshotConsumer(self, self.session_id,
                                                       turn_token=self.presentation.turns.sequence))

    async def input_delivery(self, *, include_history: bool = False) -> DeliveryView:
        coordination = self.coordination
        authority = ClientSessionRequest(self, self.session_id)
        overview = await self.controller.transcripts.read(ReadOwnerOperation(
            coordination.wire_root, coordination.thread, InputDeliveryRead(include_history=include_history),
        ))
        self.require_owner(coordination, authority)
        return ReadDeliveryView(overview)


class OwnerPrompts(CoordinationIdentity):
    supports_images = True

    async def prepare_command(self, command: PromptRequest, authority: ClientSessionRequest, scope: QueueScope) -> PromptRequest:
        coordination = self.coordination
        self.require_owner(coordination, authority)
        comms = await self.controller.transcripts.service(coordination.wire_root)
        origin = await asyncio.to_thread(self.queue_attachment.capture_human_input, comms, scope)
        self.require_owner(coordination, authority)
        return replace(command, origin=origin)

    def prompt_settlement(self, authority: ClientSessionRequest) -> Callable[[], None]:
        coordination = self.coordination

        def settle() -> None:
            self.controller.start_operation(self.reconcile_turn(coordination, authority))

        return settle

    async def reconcile_turn(self, coordination: CoordinationChangedUpdate, authority: ClientSessionRequest) -> None:
        self.require_owner(coordination, authority)
        await self.thread_read().reconcile(self.controller.transcripts)


class OwnerWrites(CoordinationIdentity):
    async def update_project(self, path: str) -> str:
        authority = ClientSessionRequest(self, self.session_id)
        coordination = self.coordination
        comms = await self.controller.transcripts.service(coordination.wire_root)
        self.require_owner(coordination, authority)
        result = await asyncio.to_thread(comms.threads.set_project, coordination.thread, path)
        self.require_owner(coordination, authority)
        worktree = Checkout(Path(result.current))
        self.receive_coordination(replace(self.coordination, worktree=worktree))
        self.project_root_path = worktree.path
        self.events.publish(core_events.CommsUpdated(self.coordination, self.session_id))
        return result.current

    async def rename_coordination(self, display_name: str) -> None:
        if not self.session.accepts_session(self.session_id):
            return
        coordination = self.coordination
        wire_root = coordination.wire_root
        authority = ClientSessionRequest(self, self.session_id)
        owner = coordination.owner
        comms = await self.controller.transcripts.service(wire_root)
        self.require_owner(coordination, authority)
        result = await asyncio.to_thread(
            comms.threads.rename_managed_thread, coordination.thread, display_name, owner=owner)
        self.require_owner(coordination, authority)
        self.receive_coordination(replace(
            self.coordination, thread=replace(self.coordination.thread, name=result.current),
            title=display_name))
        self.events.publish(core_events.CommsUpdated(self.coordination, self.session_id))


class CoordinatedSessionAgent(OwnerRequests, OwnerReads, OwnerWrites, OwnerPrompts):
    """The SDK-selected agent composes requests, captured reads and owner writes."""
