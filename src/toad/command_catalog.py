"""One derived command view joins ACP advertisements and local declarations."""

from dataclasses import dataclass
from collections.abc import Awaitable, Sequence
from typing import TYPE_CHECKING

from toad.slash_command import AgentAdvertisedCommand, CommandPresentation, LocalCommand, SlashCommand
from toad.target_commands import CommandContextChanged, TargetContext, ThreadCommand

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation


@dataclass(frozen=True)
class CommandCatalog:
    """The projected choices, read once on the preparation worker: a command's applicability
    can ask Core (a remote one over the connector), so it is never evaluated on the event loop."""

    entries: tuple[CommandPresentation, ...]
    commands: list[SlashCommand]
    target_choices: tuple
    context: TargetContext | None = None

    @classmethod
    async def read(cls, app, advertised: Sequence[AgentAdvertisedCommand],
                   context: Awaitable[TargetContext]):
        """Acquire one operation's projection through the shared read worker.

        This value is consumed by a refresh or execution and then released;
        widgets retain completion display resources, never applicability.
        """
        from agent_comms.errors import UnregisteredThreadError

        # Local declaration spelling remains authoritative when unavailable.
        commands = {command.command: command for command in advertised}
        try:
            target = await context
            definitions = await app.preparation.run_thread(target.available_actions)
        except UnregisteredThreadError:
            # An unbound or shell-only view has no backend thread. The session
            # identity and the registry query, not a UI-side presence read, own that fact.
            return await app.preparation.run_thread(cls.joined, commands)
        for definition in definitions:
            command = ThreadCommand(definition)
            commands[command.command] = command
        return await app.preparation.run_thread(cls.joined, commands, target)

    @classmethod
    def joined(cls, commands: dict[str, CommandPresentation], *context: TargetContext):
        """Local declarations join last, so their spelling stays authoritative."""
        for member in SlashCommand.members_with(LocalCommand):
            command = member()
            commands[command.command] = command
        entries = tuple(sorted(commands.values(), key=lambda command: command.command))
        target = context[0] if context else None
        return cls(
            entries,
            [choice for command in entries for choice in command.completion(target)],
            tuple(choice for command in entries for choice in command.target_choices(target)),
            target,
        )

    @classmethod
    async def execute(cls, text: str, conversation: Conversation) -> bool:
        try:
            catalog = await conversation.read_command_catalog()
            name, _, arguments = text.partition(" ")
            command = next((command for command in catalog.commands
                            if command.command == name), None)
            if command is None:
                return False
            return await command.parse_arguments(arguments).apply(conversation)
        except CommandContextChanged:
            # A recognized UI command must never fall through to agent input
            # because its original target disappeared during an awaited read.
            conversation.app.notify(
                "View changed; command was not run. Submit it again.", severity="warning"
            )
            return True
