"""Both composers draw one mention completion: what the cursor offers and what accepting writes."""
from agent_comms.messaging.mentions import MentionCandidate

from toad.client.mention_completion import MentionCompletion, MentionEditor

CANDIDATES = (MentionCandidate("claude-a", "claude-a"), MentionCandidate("claude-ai", "The AI"),
              MentionCandidate("pm-trainer", "pm-trainer"))


class Line(MentionEditor):
    def __init__(self, text: str) -> None:
        self.text = text

    def replace_span(self, row: int, start: int, end: int, text: str) -> None:
        self.text = self.text[:start] + text + self.text[end:]


def test_a_pending_mention_offers_matching_threads_and_writes_the_choice():
    line = Line("hi @cla, thanks")
    mention = MentionCompletion.at_cursor(line.text, 0, len("hi @cla"))
    assert [MentionCompletion.label(item) for item in mention.options(CANDIDATES)] == [
        "@claude-a", "@claude-ai — The AI"]
    mention.accept(line, "claude-ai")
    assert line.text == "hi @claude-ai, thanks"
    at_end = Line("@pm")
    MentionCompletion.at_cursor(at_end.text, 0, 3).accept(at_end, "pm-trainer")
    assert at_end.text == "@pm-trainer "


def test_a_line_with_no_mention_offers_and_writes_nothing():
    line = Line("plain text")
    mention = MentionCompletion.at_cursor(line.text, 0, len(line.text))
    assert mention.options(CANDIDATES) == ()
    mention.accept(line, "claude-a")
    assert line.text == "plain text"
