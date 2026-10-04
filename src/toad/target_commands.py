"""One contextual command projection for pointer menus and slash discovery."""

from __future__ import annotations
from toad.core import session_requests

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from functools import partial
from typing import TYPE_CHECKING, Self

from agent_comms.comms import Comms
from toad import messages
from toad.comms_root import root_is_current
from toad.slash_command import CommandPresentation, LocalCommand, SlashCommand
from agent_comms.cli_commands import TargetActionsCliCommand
from toad.thread_actions import ThreadAction

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.widgets.conversation import Conversation


@dataclass(frozen=True)
class TargetContext:
    app: ToadApp
    comms: Comms
    subject: str
    actor: str
    project: Path
    mode: str | None = None
    channel: str | None = None

    def current(self):
        if not root_is_current(self.comms.root):
            raise ValueError('Comms route changed; reopen this view')
        return self

    def available_actions(self):
        from toad.comms_root import RouteSelection
        selected = RouteSelection.capture(self.comms.root)
        self.current()
        actions = TargetActionsCliCommand(target=self.subject, channel=self.channel, project=str(self.project)).apply(self.comms)['actions']
        if RouteSelection.capture(self.comms.root) != selected:
            raise ValueError('Comms route changed during command discovery')
        return actions

    def show_menu(self, sidebar, offset):
        from toad.widgets.comms_menu import show_target_menu
        selected_screen = sidebar.app.screen
        source = sidebar.app.selected_session
        async def read():
            try:
                choices = await self.command_choices()
                if (not sidebar.is_attached or sidebar.app.selected_session is not source
                        or sidebar.observation.service is not self.comms
                        or sidebar.app.screen is not selected_screen):
                    return
                show_target_menu(selected_screen, offset, self.subject,
                    [(command.command.removeprefix('/'), command.label(self)) for command in choices],
                    {command.command.removeprefix('/'): partial(self.execute_menu, sidebar, command)
                     for command in choices})
            except (OSError, ValueError) as error:
                sidebar.notify(str(error), title='Target actions', severity='error')
        sidebar.run_worker(read(), name='target-menu', group='target-menu', exclusive=True,
                           exit_on_error=False)

    async def command_choices(self):
        from toad.command_catalog import CommandCatalog
        return (await CommandCatalog.read(self.app, (), self)).target_choices

    def execute_menu(self, sidebar, command):
        try:
            self.current()
            command.execute(self)
        except (OSError, ValueError) as error:
            sidebar.notify(str(error), title='Target action', severity='error')


class ContextualCommand(CommandPresentation, ABC):
    command: str

    def target_choices(self, context: TargetContext | None):
        return (self,) if context is not None and self.available(context) else ()

    def completion(self, context: TargetContext | None):
        return tuple(TargetSuggestion(command, context)
                     for command in self.target_choices(context))

    @abstractmethod
    def available(self, ctx: TargetContext) -> bool: ...

    @abstractmethod
    def label(self, ctx: TargetContext) -> str: ...

    @abstractmethod
    def execute(self, ctx: TargetContext) -> None: ...

    def parse_arguments(self, arguments: str) -> ContextualCommand:
        if arguments.strip():
            raise ValueError(
                "Use the current target; parameters are collected in the operation form"
            )
        return self

    async def apply(self, conversation: Conversation, ctx: TargetContext) -> bool:
        if await conversation.command_target_context() != ctx:
            raise ValueError("Command target changed; refresh this view")
        if not self.available(ctx):
            raise ValueError("Action is no longer available for this target")
        self.execute(ctx)
        conversation.update_slash_commands()
        return True


@dataclass(frozen=True)
class ThreadCommand(ContextualCommand):
    definition: dict

    @property
    def command(self):
        return '/' + self.definition['command']

    def available(self, ctx):
        return True  # Membership is the backend query; execution rechecks there.

    def label(self, ctx):
        return self.definition['label']

    def execute(self, ctx):
        ThreadAction.collect(ctx, self.definition)

class ViewCommand(ContextualCommand, SlashCommand, LocalCommand):
    @classmethod
    def parse(cls, arguments: str) -> Self:
        if arguments.strip():
            raise ValueError("This action takes its target from the current view")
        return cls()

    def label(self, ctx: TargetContext) -> str:
        return self.help


class CopyCommand(ViewCommand, declared_name="copy"):
    help = "Copy name"

    def available(self, ctx: TargetContext) -> bool:
        return True

    def execute(self, ctx: TargetContext) -> None:
        ctx.app.copy_to_clipboard(ctx.subject)


class CloseViewCommand(ViewCommand, declared_name="close_view"):
    help = "Close view"

    def available(self, ctx: TargetContext) -> bool:
        return (
            ctx.mode is not None
            and ctx.app.session_tracker.get_session(ctx.mode) is not None
        )

    def execute(self, ctx: TargetContext) -> None:
        ctx.app.session_navigation.events.publish(session_requests.SessionArchive(ctx.mode))


@dataclass(frozen=True)
class TargetSuggestion(SlashCommand):
    choice: ContextualCommand
    context: TargetContext
    hint = None

    @property
    def help(self) -> str:
        return self.choice.label(self.context)

    @property
    def command(self) -> str:
        return self.choice.command

    @classmethod
    def parse(cls, arguments: str) -> Self:
        raise ValueError("Target suggestions are projections of existing declarations")

    def parse_arguments(self, arguments: str) -> Self:
        return type(self)(self.choice.parse_arguments(arguments), self.context)

    async def apply(self, conversation: Conversation) -> bool:
        return await self.choice.apply(conversation, self.context)
