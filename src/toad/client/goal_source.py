"""A thread's goal over the comms owner path, for a viewer with no ACP session.

The snapshot is an owner read; pause, resume, clear and edit are owner requests; history is
an owner request. These are the same owner reads and requests the ACP session agent makes —
the TUI reaches them through its agent binding, the phone reaches them here — so the goal the
phone shows and changes is the one the thread's owner holds, with no copy of the goal here.
"""

from __future__ import annotations

from agent_comms.acp_extension import GoalSnapshotReply
from agent_comms.nominal.field_codec import FieldCodec
from agent_comms.planning.goal_actions import GoalAction
from agent_comms.planning.goal_history import RecordedGoalHistory
from agent_comms.planning.goal_scope import OneGoal
from agent_comms.planning.goals import Goal
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.transport.owner_connection import CapturedOwner
from agent_comms.transport.runtime_request import RuntimeRequest
from agent_comms.transport.runtime_requests import (
    EditGoalRuntimeRequest,
    GoalHistoryRuntimeRequest,
    UpdateGoalRuntimeRequest,
)
from agent_comms.transport.tools.reads import OwnerGoalRead
from agent_comms.ui_model.observation import ReadOwnerOperation

from toad.goal_controls import GoalSource


class CommsGoalSource(GoalSource):
    """One thread's goal, read and changed over comms. Bound to the thread incarnation that
    owns the goal; a channel owns none, so a conversation with no `goal_owner()` has no source."""

    def __init__(self, app, owner: ThreadIncarnation) -> None:
        self.app = app
        self.owner = owner

    async def get_goal_snapshot(self) -> GoalSnapshotReply:
        """The owner's current goal snapshot (goal + execution), read as the TUI reads it."""
        root = str(self.app.source().root)
        return await self.app.coordination_access.transcripts.read(
            ReadOwnerOperation(root, self.owner, operation=OwnerGoalRead()))

    def matches_agent(self, agent) -> bool:
        return agent is self

    def invalidate_observation(self, observation) -> None:
        observation.schedule(self)

    async def _request(self, request: RuntimeRequest) -> GoalSnapshotReply:
        """One owner request off the UI thread; its reply is the owner's fresh snapshot."""
        observed = self.app.coordination_access.observation.observed()
        payload = await self.app.preparation.run_thread(observed.owner_request, self.owner, request)
        return FieldCodec.decode(GoalSnapshotReply, payload)

    async def act(self, action: type[GoalAction], goal: Goal) -> GoalSnapshotReply:
        """Pause, resume or clear the goal: the action the execution names, fenced to the goal
        revision the viewer saw."""
        return await self._request(UpdateGoalRuntimeRequest(
            thread=self.owner.name, captured=CapturedOwner(self.owner),
            goal_id=goal.id, expected_revision=goal.revision, status=action))

    async def edit(self, goal: Goal, text: str) -> GoalSnapshotReply:
        return await self._request(EditGoalRuntimeRequest(
            thread=self.owner.name, captured=CapturedOwner(self.owner),
            goal_id=goal.id, expected_revision=goal.revision, text=text))

    async def history(self, goal: Goal) -> RecordedGoalHistory:
        observed = self.app.coordination_access.observation.observed()
        payload = await self.app.preparation.run_thread(
            observed.owner_request, self.owner,
            GoalHistoryRuntimeRequest(thread=self.owner.name, goal_id=OneGoal(goal.id)))
        return FieldCodec.decode(RecordedGoalHistory, payload)
