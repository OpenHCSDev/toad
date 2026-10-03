"""One derived command view joins ACP advertisements and local declarations."""

from dataclasses import dataclass
from collections.abc import Sequence
from typing import TYPE_CHECKING

from toad.slash_command import AgentAdvertisedCommand, CommandPresentation, LocalCommand, SlashCommand
from toad.target_commands import TargetContext, ThreadCommand

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation


@dataclass(frozen=True)
class CommandCatalog:
    advertised: Sequence[AgentAdvertisedCommand]
    context: TargetContext | None = None

    @property
    def entries(self) -> tuple[CommandPresentation, ...]:
        # Local declaration spelling remains authoritative when unavailable.
        commands = {command.command: command for command in self.advertised}
        if self.context is not None:
            for definition in self.context.current().available_actions():
                command = ThreadCommand(definition)
                commands[command.command] = command
        for member in SlashCommand.members_with(LocalCommand):
            command = member()
            commands[command.command] = command
        return tuple(sorted(commands.values(), key=lambda command: command.command))

    @property
    def commands(self) -> list[SlashCommand]:
        actions = ()
        return [choice for command in self.entries
                for choice in command.completion(self.context, actions)]

    @property
    def target_choices(self):
        actions = ()
        return tuple(choice for command in self.entries
                     for choice in command.target_choices(self.context, actions))

    async def execute(self, text: str, conversation: Conversation) -> bool:
        name, _, arguments = text.partition(" ")
        command = next((command for command in self.entries
                        if command.command == name), None)
        if command is None:
            return False
        try:
            return await command.parse_arguments(arguments).apply(conversation)
        except (OSError, ValueError) as error:
            conversation.flash(str(error), style="error")
            return True
