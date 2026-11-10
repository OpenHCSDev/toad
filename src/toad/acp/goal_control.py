"""Native goal requests built by the client that holds the original owner authority."""

from abc import abstractmethod

from agent_comms.acp_extension import GoalSnapshotReply
from agent_comms.nominal.field_codec import FieldCodec
from agent_comms.transport.owner_connection import CapturedOwner
from agent_comms.planning.goal_actions import GoalAction
from agent_comms.planning.goal_control import GoalControlSource
from agent_comms.planning.goals import Goal, GoalDeclaration
from agent_comms.transport.serving.served_requests import GoalReply
from agent_comms.transport.runtime_requests import (
    RetryGoalRuntimeRequest,
    SetGoalRuntimeRequest,
    UpdateGoalRuntimeRequest,
)
from agent_comms.transport.runtime_request import AttachedRuntimeRequest
from pydantic import JsonValue

from toad.acp.client_session import OwnerRequest


class ClientGoalControls(GoalControlSource[OwnerRequest, GoalAction[GoalDeclaration], Goal, GoalDeclaration]):
    @abstractmethod
    async def request_owner(
        self, captured: OwnerRequest, operation: AttachedRuntimeRequest,
    ) -> JsonValue: ...

    async def change_goal_control(
        self, authority: OwnerRequest, action: type[GoalAction[GoalDeclaration]], goal: Goal,
    ) -> GoalDeclaration:
        thread = authority.coordination.thread
        reply = await self.request_owner(authority, UpdateGoalRuntimeRequest(
            thread=thread.name, captured=CapturedOwner(thread), status=action,
            goal_id=goal.id, expected_revision=goal.revision,
        ))
        return FieldCodec.decode(GoalSnapshotReply, reply).goal

    async def set_goal_control(self, authority: OwnerRequest, text: str) -> GoalDeclaration:
        thread = authority.coordination.thread
        reply = await self.request_owner(authority, SetGoalRuntimeRequest(
            thread=thread.name, captured=CapturedOwner(thread), text=text,
        ))
        return FieldCodec.decode(GoalReply, reply).goal

    async def retry_goal_control(self, authority: OwnerRequest, goal: Goal) -> GoalDeclaration:
        thread = authority.coordination.thread
        reply = await self.request_owner(authority, RetryGoalRuntimeRequest(
            thread=thread.name, captured=CapturedOwner(thread),
            goal_id=goal.id, expected_revision=goal.revision,
        ))
        return FieldCodec.decode(GoalReply, reply).goal
