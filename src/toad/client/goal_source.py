"""A thread's goal over the comms owner path, for a view with no live agent session.

The snapshot is an owner read; set, pause, resume, retry, clear and edit are owner requests;
history is an owner request. Core answers each one through the thread's owner binding: a live
native owner's runtime, the bus for an external CLI's goal (the bus holds it and wakes the CLI
through its inbox), or nobody for a native owner that is not running. These are the owner
reads and requests the ACP session agent makes; a TUI view with an agent reaches them through
its agent binding, every other view here, so the goal both frontends show and change is the
one its owner holds, with no copy of it here.
"""

from __future__ import annotations

from agent_comms.acp_extension import GoalSnapshotReply
from agent_comms.nominal.field_codec import FieldCodec, GoalId
from agent_comms.planning.goal_actions import GoalAction
from agent_comms.planning.goal_control import GoalControlSource
from agent_comms.planning.goal_history import RecordedGoalHistory
from agent_comms.planning.goal_scope import OneGoal
from agent_comms.planning.goals import Goal, GoalDeclaration
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.registry.thread_presentation import ThreadOwnerBinding
from agent_comms.transport.owner_connection import CapturedOwner
from agent_comms.transport.runtime_request import RuntimeRequest
from agent_comms.transport.runtime_requests import (
    EditGoalRuntimeRequest,
    GoalHistoryRuntimeRequest,
    GoalReply,
    RetryGoalRuntimeRequest,
    SetGoalRuntimeRequest,
    UpdateGoalRuntimeRequest,
)
from agent_comms.transport.tools.reads import OwnerGoalRead
from agent_comms.ui_model.observation import ReadOwnerOperation
from pydantic import JsonValue

from toad.agent_binding import NoAgentConnection
from toad.goal_controls import GoalSource


class CommsGoalSource(
    GoalSource, GoalControlSource[ThreadIncarnation, GoalAction[GoalDeclaration], Goal, GoalDeclaration],
):
    """One thread's goal, read and changed over comms. Bound to the thread incarnation that
    owns the goal; a channel owns none, so a conversation with no `goal_owner()` has no source.
    Its captured authority is that incarnation, as an agent's is its client session."""

    def __init__(self, app, owner: ThreadIncarnation, root: str) -> None:
        self.app = app
        self.owner = owner
        self.root = root

    async def get_goal_snapshot(self) -> GoalSnapshotReply:
        """The owner's current goal snapshot (goal + execution), read as the TUI reads it.

        The registry's owner binding selects the reader, as it selects every owner read: a
        live native owner and an external CLI (whose goal the bus holds) are read over comms;
        a native owner that is not running has no owner to ask, so it answers the no-owner goal
        the TUI shows for a view without an agent instead of a request Core can only refuse."""
        binding = await self.owner_binding()
        return await binding.select_answer(
            unowned=NoAgentConnection().get_goal_snapshot,
            native=self.read_owner_goal, held=self.read_owner_goal)()

    async def owner_binding(self) -> ThreadOwnerBinding:
        """Who answers this goal's thread, as Core presents it: the registry lease, read with
        the thread's kind (an external CLI's goal is the bus's)."""
        read = await self.app.coordination_access.transcripts.thread_presentation(self.root, self.owner.name)
        return read.raised().answering_binding()

    async def read_owner_goal(self) -> GoalSnapshotReply:
        return await self.app.coordination_access.transcripts.read(
            ReadOwnerOperation(self.root, self.owner, operation=OwnerGoalRead()))

    def matches_agent(self, agent) -> bool:
        return agent is self

    def invalidate_observation(self, observation) -> None:
        observation.schedule(self)

    def presentation_changed(self, observation) -> None:
        """Core announces a goal change as a change of its thread's presentation."""
        observation.invalidate()

    async def _request(self, request: RuntimeRequest) -> JsonValue:
        """One owner request off the UI thread; Core reaches the owner the binding names."""
        observed = self.app.coordination_access.observation.observed()
        return await self.app.preparation.run_thread(observed.owner_request, self.owner, request)

    # The goal writes and history every goal source answers (GoalSource)

    async def update_goal(self, action: type[GoalAction], text: str = "") -> GoalDeclaration:
        return await action.submit_control(self, self.owner, text)

    async def edit_goal(self, goal: Goal, text: str) -> Goal:
        reply = await self._request(EditGoalRuntimeRequest(
            thread=self.owner.name, captured=CapturedOwner(self.owner),
            goal_id=goal.id, expected_revision=goal.revision, text=text))
        return FieldCodec.decode(GoalSnapshotReply, reply).goal.require()

    async def get_goal_history(self, goal_id: GoalId) -> RecordedGoalHistory:
        reply = await self._request(GoalHistoryRuntimeRequest(thread=self.owner.name, goal_id=OneGoal(goal_id)))
        return FieldCodec.decode(RecordedGoalHistory, reply)

    # The captured-authority controls GoalAction.submit_control drives (GoalControlSource)

    async def observed_goal(self, authority: ThreadIncarnation) -> GoalDeclaration:
        return (await self.get_goal_snapshot()).goal

    async def change_goal_control(
        self, authority: ThreadIncarnation, action: type[GoalAction[GoalDeclaration]], goal: Goal,
    ) -> GoalDeclaration:
        """Pause, resume or clear the goal, fenced to the goal revision the viewer saw."""
        reply = await self._request(UpdateGoalRuntimeRequest(
            thread=authority.name, captured=CapturedOwner(authority),
            goal_id=goal.id, expected_revision=goal.revision, status=action))
        return FieldCodec.decode(GoalSnapshotReply, reply).goal

    async def set_goal_control(self, authority: ThreadIncarnation, text: str) -> GoalDeclaration:
        reply = await self._request(SetGoalRuntimeRequest(
            thread=authority.name, captured=CapturedOwner(authority), text=text))
        return FieldCodec.decode(GoalReply, reply).goal

    async def retry_goal_control(self, authority: ThreadIncarnation, goal: Goal) -> GoalDeclaration:
        reply = await self._request(RetryGoalRuntimeRequest(
            thread=authority.name, captured=CapturedOwner(authority),
            goal_id=goal.id, expected_revision=goal.revision))
        return FieldCodec.decode(GoalReply, reply).goal
