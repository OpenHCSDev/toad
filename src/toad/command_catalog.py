"""One derived command view joins ACP advertisements and local declarations."""

from dataclasses import dataclass

from toad.slash_command import AgentAdvertisedCommand, LocalCommand, SlashCommand
from toad.target_commands import TargetContext, TargetLocal, target_completion


@dataclass(frozen=True)
class CommandCatalog:
    advertised: list[AgentAdvertisedCommand]
    context: TargetContext | None = None

    @property
    def commands(self) -> list[SlashCommand]:
        # Declaration spelling wins over an agent's external advertisement.
        commands = {command.command: command for command in self.advertised}
        if self.context is not None:
            commands.update((command.command, command)
                            for command in target_completion(self.context))
        for member in SlashCommand.members_with(LocalCommand):
            if not issubclass(member, TargetLocal):
                command = member()
                commands[command.command] = command
        return sorted(commands.values(), key=lambda command: command.command)
