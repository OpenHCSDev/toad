"""A Toad agent whose goal owner is a test script, for goal bar and goal screen tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agent_comms.goal_actions import GoalAction
from agent_comms.goal_mentions import bind_goal_mentions
from agent_comms.goal_presentation import GoalSnapshot, IdleGoalExecution, ThreadGoalExecution
from agent_comms.goal_states import ActiveGoal
from agent_comms.goals import Goal, GoalDeclaration
from agent_comms.registry_document import RegistrySnapshot
from agent_comms.threads import Thread

from toad.acp.agent import Agent
from toad.app import ToadApp
from toad.agent_schema import AgentDefinition


def published_goal(text: str, goal_id: str, **fields) -> Goal:
    """A goal as the goal store first publishes it (Core SetGoalAction.create)."""
    return Goal(text=text, id=goal_id, published_seq=fields.pop("published_seq", 1),
                revision=fields.pop("revision", 1), **fields)


def bound_mentions(goal: Goal, owner: Thread, registry: RegistrySnapshot) -> Goal:
    """The goal with the mention bindings Core freezes when it publishes it (SetGoalAction.create)."""
    return replace(goal, mention_source=bind_goal_mentions(goal.text, goal.id, goal.revision, owner, registry))


class ScriptedGoalOwner(Agent):
    """A process-less agent that answers goal reads and writes from ``goal`` and ``execution``.

    Every goal request is recorded in ``requests`` as (kind, details). A test sets ``goal``,
    ``execution`` and ``reject`` to change what the owner answers next. A control action
    (Retry, Pause, ...) leaves the goal active.
    """

    def __init__(self, app: ToadApp, goal: GoalDeclaration,
                 execution: ThreadGoalExecution = IdleGoalExecution(), *,
                 history: list[dict] | None = None):
        super().__init__(Path(app.project_dir), AgentDefinition("goal-owner", "goal-owner", {"*": "true"}),
                         "goal-owner", app_events=app.events, transcripts=app.coordination_access.transcripts)
        self.goal, self.execution, self.history = goal, execution, history or []
        self.requests: list[tuple[str, object]] = []
        self.reject = False

    async def get_goal_snapshot(self):
        return GoalSnapshot(self.goal, self.execution)

    async def update_goal(self, action: type[GoalAction], text: str = ""):
        self.requests.append(("update", action))
        self.goal = replace(self.goal, state=ActiveGoal())
        return self.goal

    async def edit_goal(self, expected, text):
        self.requests.append(("edit", (expected.id, expected.revision, text)))
        if self.reject:
            raise ValueError("Goal changed; refresh before editing")
        self.goal = replace(self.goal, text=text, revision=self.goal.revision + 1)
        return self.goal

    async def get_goal_history(self, goal_id):
        assert goal_id == self.goal.id
        return self.history
