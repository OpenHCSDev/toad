"""Typed command candidates own one scoring lifetime: which commands a typed `/query`
offers and in what order. No toolkit; each frontend draws the ranked matches."""
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Sequence

from toad.client.fuzzy import FuzzySearch
from toad.slash_command import SlashCommand


@dataclass(frozen=True)
class CommandMatch:
    command: SlashCommand
    score: float
    offsets: Sequence[int]


class SlashCommandResults(FuzzySearch):
    """Inherit matching/cache behavior; rank the command catalog for a typed query."""

    def ranked(self, text: str, commands: Iterable[SlashCommand]) -> list[CommandMatch]:
        query = text.lstrip("/").casefold().rstrip()
        ordered = sorted(commands, key=lambda command: command.command.casefold())
        if not query:
            return [CommandMatch(command, 1.0, ()) for command in ordered]
        scores = [CommandMatch(command, *self.match(query, command.command[1:])) for command in ordered]
        return sorted(
            (match for match in scores if match.score),
            key=lambda match: match.score * (2 if match.command.command.casefold().startswith(f"/{query}") else 1),
            reverse=True,
        )
