"""Owner operations inherited by the operational ACP agent."""
from __future__ import annotations

import asyncio
from pydantic import JsonValue

from agent_comms.acp_extension import CoordinationChangedUpdate
from agent_comms.goal_actions import GoalAction
from agent_comms.goal_history import RecordedGoalHistory
from agent_comms.goal_presentation import GoalSnapshot
from agent_comms.goals import Goal, GoalDeclaration
from agent_comms.order_tools import InputDeliveryRead
from agent_comms.owner_connection import socket_path
from agent_comms.runtime import RuntimeConnection
from agent_comms.nominal.field_codec import FieldCodec, GoalId
from agent_comms.ui_model.delivery import DeliveryView, ReadDeliveryView
from agent_comms.ui_model.observation import ReadOwnerOperation
from toad.agent import AgentBase
from .agent_controller import AgentController
from .client_session import ClientSessionRequest


class SessionAgent(AgentBase):
    """The agent owns its coordinator identity and native owner requests."""

    controller: AgentController
    coordination: CoordinationChangedUpdate | None = None

    async def request_owner(self, method: str, **params: JsonValue):
        if self.coordination is None:
            raise ValueError("This action requires an agent-comms thread.")
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

    def require_owner(self, coordination: CoordinationChangedUpdate, authority: ClientSessionRequest):
        if authority.retired or self.coordination is None:
            raise ValueError("The connected owner session retired; refresh its state.")
        if (self.coordination.wire_root, self.coordination.thread) != (coordination.wire_root, coordination.thread):
            raise ValueError("The owner identity changed while preparing the request.")

    async def input_delivery(self, *, include_history: bool = False) -> DeliveryView:
        """Read delivery notices for the captured original coordinator."""
        coordination = self.coordination
        if coordination is None:
            return DeliveryView()
        authority = ClientSessionRequest(self, self.session_id)
        overview = await self.controller.transcripts.read(ReadOwnerOperation(
            coordination.wire_root, coordination.thread, InputDeliveryRead(include_history=include_history),
        ))
        self.require_owner(coordination, authority)
        return ReadDeliveryView(overview)

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
