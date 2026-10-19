"""Goal text uses the same mention syntax and navigation as wire messages."""
from agent_comms.mentions import MentionCandidate
from toad.markdown_links import LinkContext
from toad.widgets.selection import ChangingText

from toad.widgets.inline_message import inline_message
from toad.widgets.linked_rows import OpensLinks, ReferenceRendering


def goal_mention_candidates(observed) -> tuple[MentionCandidate, ...]:
    return tuple(MentionCandidate(row.name, row.title)
                 for row in observed.sidebar.threads.rows.values())


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
