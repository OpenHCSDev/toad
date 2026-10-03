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
    entries: tuple[CommandPresentation, ...]
    context: TargetContext | None = None

    @classmethod
    async def read(cls, app, advertised: Sequence[AgentAdvertisedCommand],
                   context: TargetContext | None = None):
        """Acquire one operation's projection through the shared read worker.

        This value is consumed by a refresh or execution and then released;
        widgets retain completion display resources, never applicability.
        """
        from agent_comms.errors import UnregisteredThreadError

        # Local declaration spelling remains authoritative when unavailable.
        commands = {command.command: command for command in advertised}
        if context is not None:
            try:
                definitions = await app.preparation.run_thread(context.available_actions)
            except UnregisteredThreadError:
                # A shell-only view has no backend thread. The registry query,
                # rather than a second UI-side presence read, owns that fact.
                context = None
            else:
                for definition in definitions:
                    command = ThreadCommand(definition)
                    commands[command.command] = command
        for member in SlashCommand.members_with(LocalCommand):
            command = member()
            commands[command.command] = command
        return cls(tuple(sorted(commands.values(), key=lambda command: command.command)), context)

    @property
    def commands(self) -> list[SlashCommand]:
        return [choice for command in self.entries
                for choice in command.completion(self.context)]

    @property
    def target_choices(self):
        return tuple(choice for command in self.entries
                     for choice in command.target_choices(self.context))

    async def execute(self, text: str, conversation: Conversation) -> bool:
        name, _, arguments = text.partition(" ")
        command = next((command for command in self.commands
                        if command.command == name), None)
        if command is None:
            return False
        try:
            return await command.parse_arguments(arguments).apply(conversation)
        except (OSError, ValueError) as error:
            conversation.flash(str(error), style="error")
            return True
