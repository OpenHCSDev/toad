"""Goal text uses the same mention syntax and navigation as wire messages."""
from agent_comms.goals import NoGoalProgress
from agent_comms.mentions import MentionCandidate
from toad.markdown_links import LinkContext, ReferenceRendering
from toad.widgets.selection import ChangingText

from toad.widgets.inline_message import inline_message
from toad.widgets.transcript_lines import OpensLinks


def goal_mention_candidates(app) -> tuple[MentionCandidate, ...]:
    sidebar = app.coordination_access.sidebar
    if sidebar is None:
        return ()
    return tuple(MentionCandidate(row.name, row.title) for row in sidebar.threads.rows.values())


class GoalText(ReferenceRendering, OpensLinks, ChangingText):
    def __init__(self, text: str = "", **kwargs):
        self.goal_text = text
        super().__init__(text, markup=False, **kwargs)

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self.invalidate_lines)
        self.update_goal_text(self.goal_text)

    def invalidate_lines(self, change=None) -> None:
        self.update_goal_text(self.goal_text)

    def update_goal_text(self, text: str) -> None:
        self.goal_text = text
        self.update(inline_message(text, self.app.colours, LinkContext.containing(self)))


class GoalProgressText(GoalText):
    """A progress member controls this view; the widget never infers absence."""
    def __init__(self, progress=NoGoalProgress(), *, prefix="", **kwargs):
        self.progress = progress
        self.prefix = prefix
        super().__init__(**kwargs)

    def on_mount(self):
        super().on_mount()
        self.progress.present(self)

    def update_progress(self, progress):
        self.progress = progress
        if self.is_mounted:
            progress.present(self)

    def show_progress(self, text):
        self.update_goal_text(self.prefix + text)
        self.display = True

    def hide_progress(self):
        self.update_goal_text("")
        self.display = False
