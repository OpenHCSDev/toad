"""A goal bar's control for one declared interaction."""

from toad.widgets.goal_bar import GoalControl


def goal_control(bar, interaction) -> GoalControl:
    return next(control for control in bar.query(GoalControl) if control.interaction is interaction)
