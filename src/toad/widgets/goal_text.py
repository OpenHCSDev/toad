"""Goal text uses the same mention syntax and navigation as wire messages."""
from agent_comms.mentions import MentionCandidate, ThreadMention
from textual.widgets import Static

from toad.widgets.inline_message import inline_message
from toad.widgets.transcript_lines import OpensLinks


def goal_mention_candidates(app) -> tuple[MentionCandidate, ...]:
    sidebar = app.coordination_access.sidebar
    if sidebar is None:
        return ()
    return tuple(MentionCandidate(row.name, row.title) for row in sidebar.threads.rows.values())


class GoalText(OpensLinks, Static):
    def __init__(self, text: str = "", **kwargs):
        self.goal_text = text
        super().__init__(text, markup=False, **kwargs)

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self._theme_changed)
        self.update_goal_text(self.goal_text)

    def _theme_changed(self, _theme) -> None:
        self.update_goal_text(self.goal_text)

    def update_goal_text(self, text: str) -> None:
        self.goal_text = text
        names = {candidate.name for candidate in goal_mention_candidates(self.app)}
        mentions = ThreadMention.find(
            text, lambda name: name if name in names else None
        )
        self.update(inline_message(text, self.app.colours, mentions))
