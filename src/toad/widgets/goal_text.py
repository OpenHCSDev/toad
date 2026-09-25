"""Goal text uses the same mention syntax and navigation as wire messages."""

from agent_comms import MentionCandidate, ThreadMention
from textual.widgets import Static

from toad.widgets.comms_sidebar import SelectTarget
from toad.widgets.inline_message import inline_message


def goal_mention_candidates(app) -> tuple[MentionCandidate, ...]:
    snapshot = getattr(app, "_sidebar_snapshot", None)
    if snapshot is None:
        return ()
    return tuple(
        MentionCandidate(person.thread.name, person.presentation.title)
        for person in snapshot.threads
    )


class GoalText(Static):
    def __init__(self, text: str = "", **kwargs):
        self.goal_text = text
        super().__init__(text, markup=False, **kwargs)

    def on_mount(self) -> None:
        self.update_goal_text(self.goal_text)

    def update_goal_text(self, text: str) -> None:
        self.goal_text = text
        names = {candidate.name for candidate in goal_mention_candidates(self.app)}
        mentions = ThreadMention.find(
            text, lambda name: name if name in names else None
        )
        self.update(inline_message(text, mentions))

    def action_open_target(self, target: str) -> None:
        self.post_message(SelectTarget(target, "thread"))

    def action_open_url(self, url: str) -> None:
        self.app.open_url(url)
