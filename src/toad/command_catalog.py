"""One derived command view joins ACP advertisements and local declarations."""

from dataclasses import dataclass
from collections.abc import Awaitable, Sequence
from functools import partial

from agent_comms.errors import UnregisteredThreadError
from formbridge.operations import ExclusiveKind, OperationKind
from toad.client.commands import (CommandContextChanged, CommandRefused, ConversationCommands, LocalCommand,
                                  ViewLocalCommand)
from toad.client.menu_entry import MenuEntry
from toad.slash_command import AgentAdvertisedCommand, CommandPresentation, SlashCommand
from toad.target_commands import TargetContext, ThreadCommand


class CommandRead(OperationKind, ExclusiveKind):
    """Reads a conversation's command catalog for its composer; a newer read supersedes it.
    Textual runs it as the view's exclusive "command-catalog" worker, Qt as the app's
    operation."""


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
                   context: Awaitable[TargetContext], local: type[LocalCommand]):
        """Acquire one operation's projection through the shared read worker.

        `local` is the family of local commands the reading conversation runs.
        This value is consumed by a refresh or execution and then released;
        widgets retain completion display resources, never applicability.
        """
        # Local declaration spelling remains authoritative when unavailable.
        commands = {command.command: command for command in advertised}
        try:
            target = await context
            definitions = await app.preparation.run_thread(target.available_actions)
        except UnregisteredThreadError:
            # An unbound or shell-only view has no backend thread. The session
            # identity and the registry query, not a UI-side presence read, own that fact.
            return await app.preparation.run_thread(cls.joined, commands, local)
        for definition in definitions:
            command = ThreadCommand(definition)
            commands[command.command] = command
        return await app.preparation.run_thread(cls.joined, commands, local, target)

    @classmethod
    def joined(cls, commands: dict[str, CommandPresentation], local: type[LocalCommand],
               *context: TargetContext):
        """Local declarations join last, so their spelling stays authoritative."""
        for member in SlashCommand.members_with(local):
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
    async def pointer_menu(cls, context: TargetContext) -> tuple[MenuEntry, ...]:
        """What a right-click or a held finger on a channel or thread offers, in every
        frontend: the commands its target context applies, each run in that context.
        Textual's sidebar rows show these in an `ActionMenu`, Qt's in its menu panel."""
        choices = (await cls.read(context.app, (), context.acquired(), ViewLocalCommand)).target_choices
        return tuple(MenuEntry(command.label(context), partial(context.execute_command, command))
                     for command in choices)

    def recognizes(self, text: str) -> bool:
        """Whether typed text starts with one of these commands."""
        name = text.partition(" ")[0]
        return any(command.command == name for command in self.commands)

    def command_named(self, name: str) -> SlashCommand:
        return next(command for command in self.commands if command.command == name)

    @classmethod
    async def execute(cls, text: str, conversation: ConversationCommands) -> bool:
        """Run typed text as the conversation's command; False when it names none, so the
        text goes on as a message. A recognized command never falls through as text."""
        if not text.startswith("/"):
            return False
        try:
            catalog = await conversation.read_command_catalog()
            if not catalog.recognizes(text):
                return False
            name, _, arguments = text.partition(" ")
            return await catalog.command_named(name).parse_arguments(arguments).apply(conversation)
        except CommandContextChanged:
            # Its original target disappeared during an awaited read.
            conversation.app.show_warning("View changed; command was not run. Submit it again.",
                                          text.partition(" ")[0])
            return True
        except CommandRefused as refusal:
            conversation.flash_error(str(refusal))
            return True
