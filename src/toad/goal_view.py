"""The original view capabilities consumed by source-bound goal controls."""

from pathlib import Path

from agent_comms.planning.goal_presentation import GoalExecutionControls
from agent_comms.ui_model.goal import GoalDisplay
from textual.widget import Widget
from toad.agent_binding import AgentConnection
from toad.app_node import ToadNode
from toad.core_event_carrier import CoreEventReceiver
from toad.session_observation import GoalObservation
from toad.widgets.flash import Flash


class GoalCollapse:
    """The goal document owns whether its controls are collapsed."""

    collapsed: bool


class GoalView[Controls](CoreEventReceiver, ToadNode):
    """A real conversation retains its existing fields and source binding."""

    agent_binding: AgentConnection
    goal_controls: Controls
    goal_display: GoalDisplay
    goal_execution: GoalExecutionControls
    goal_observation: GoalObservation
    goal_bar: GoalCollapse
    feedback: Flash
    prompt: Widget
    project_path: Path
