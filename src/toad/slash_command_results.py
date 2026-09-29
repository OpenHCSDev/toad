"""Typed command candidates own one scoring and row-production lifetime."""
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Sequence

from textual.content import Content, Span
from textual.widgets.option_list import Option

from toad.fuzzy import FuzzySearch
from toad.slash_command import SlashCommand
from toad.visuals.columns import Columns


@dataclass(frozen=True)
class CommandMatch:
    command: SlashCommand
    score: float
    offsets: Sequence[int]


class SlashCommandResults(FuzzySearch):
    """Inherit matching/cache behavior; produce the command catalog's display view."""

    def options(self, text: str, commands: Iterable[SlashCommand]) -> Iterable[Option]:
        query = text.lstrip("/").casefold().rstrip()
        ordered = sorted(commands, key=lambda command: command.command.casefold())
        self.cache.grow(len(ordered))
        if query:
            scores = [CommandMatch(command, *self.match(query, command.command[1:])) for command in ordered]
            ranked = sorted(
                (match for match in scores if match.score),
                key=lambda match: match.score * (2 if match.command.command.casefold().startswith(f"/{query}") else 1),
                reverse=True,
            )
        else:
            ranked = [CommandMatch(command, 1.0, ()) for command in ordered]
        columns = Columns("auto", "flex")
        for match in ranked:
            command = match.command
            name = Content.styled(command.command, "$text-success").add_spans(
                Span(index + 1, index + 2, "underline not dim") for index in match.offsets
            )
            yield Option(columns.add_row(name, Content.styled(command.help, "dim")), id=command.command)
