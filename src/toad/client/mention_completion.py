"""The @mention a composer's cursor is typing: which thread names it offers, how each
option reads, and what accepting one writes into the line. Textual's channel prompt and
Qt's channel composer draw the same completion from here."""

from __future__ import annotations

from dataclasses import dataclass

from agent_comms.messaging.mentions import MentionCandidate, MentionQuery


class MentionEditor:
    """The editor a mention is accepted into: holds the current mention candidates and
    replaces one span of one line when a candidate is accepted."""

    mention_candidates: tuple[MentionCandidate, ...] = ()

    def set_mention_candidates(self, candidates: tuple[MentionCandidate, ...]) -> None:
        """Replace the offered mention candidates and refresh when the set changes."""
        if candidates != self.mention_candidates:
            self.mention_candidates = candidates
            self.mention_candidates_changed()

    def mention_candidates_changed(self) -> None:
        """Refresh the frontend's mention completion popup after `mention_candidates` updates."""
        raise NotImplementedError

    def replace_span(self, row: int, start: int, end: int, text: str) -> None:
        raise NotImplementedError


class MentionCompletion:
    """What the cursor's line offers; a line with no pending mention offers nothing."""

    title = "Mention a thread · Tab to insert"

    @staticmethod
    def at_cursor(line: str, row: int, column: int) -> MentionCompletion:
        query = MentionQuery.at_cursor(line, column)
        return MentionCompletion() if query is None else PendingMention(query, row, line)

    def options(self, candidates: tuple[MentionCandidate, ...]) -> tuple[MentionCandidate, ...]:
        return ()

    def accept(self, editor: MentionEditor, name: str) -> None:
        """Nothing is being typed, so nothing is replaced."""

    @staticmethod
    def label(candidate: MentionCandidate) -> str:
        return f"@{candidate.name}" + (f" — {candidate.title}" if candidate.title != candidate.name else "")


@dataclass(frozen=True)
class PendingMention(MentionCompletion):
    """An @ the cursor is typing on one line: the span accepting a name replaces."""

    query: MentionQuery
    row: int
    line: str

    def options(self, candidates: tuple[MentionCandidate, ...]) -> tuple[MentionCandidate, ...]:
        return self.query.candidates(candidates)

    def accept(self, editor: MentionEditor, name: str) -> None:
        editor.replace_span(self.row, self.query.start, self.query.end, self.replacement(name))

    def replacement(self, name: str) -> str:
        """The mention, with a space after it unless punctuation or a space already follows."""
        following = self.line[self.query.end:]
        spaced = not following or (not following[0].isspace() and following[0] not in ".,:;!?)]}")
        return f"@{name}" + (" " if spaced else "")
