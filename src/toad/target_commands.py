"""One contextual command projection for pointer menus and slash discovery."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Self

from agent_comms.cli_verbs.cli_command import TargetAction
from agent_comms.transport.tools.sidebar import CommsTargetActionsTool

from toad.client.commands import (
    ConversationCommands,
    SharedContextualCommand,
    SharedTargetContext,
    SortCapable,
)
from toad.slash_command import CommandPresentation, LocalCommand, SlashCommand
from toad.thread_actions import ThreadAction


class TargetContext(SharedTargetContext):
    def current(self):
        self.app.coordination_access.selected(self.observed.root)
        return self

    def available_actions(self):
        access = self.app.coordination_access
        selected = access.selected(self.observed.root)
        actions = self.observed.core.call(CommsTargetActionsTool(
            project=self.project, targets=self.selection, channel=self.channel)).actions
        access.confirm(selected)
        return actions

    async def acquired(self):
        """A captured context is already acquired when a catalog reads it."""
        return self

    def execute_command(self, command):
        self.current()
        command.execute(self)


class ContextualCommand(SharedContextualCommand, CommandPresentation, ABC):

    def target_choices(self, context: TargetContext | None):
        return (self,) if context is not None and self.available(context) else ()

    def completion(self, context: TargetContext | None):
        return tuple(TargetSuggestion(command, context)
                     for command in self.target_choices(context))

    def parse_arguments(self, arguments: str) -> ContextualCommand:
        if arguments.strip():
            raise ValueError(
                "Use the current target; parameters are collected in the operation form"
            )
        return self


@dataclass(frozen=True)
class ThreadCommand(ContextualCommand):
    definition: TargetAction

    @property
    def command(self):
        return '/' + self.definition.declaration.declared_name

    def available(self, ctx):
        return True  # Membership is the backend query; execution rechecks there.

    def label(self, ctx):
        return self.definition.label

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


class DirectMessagesCommand(ViewCommand, declared_name="dm"):
    help = "Direct messages"

    def available(self, ctx: TargetContext) -> bool:
        names = ctx.selected_targets
        return len(names) == 1 and names[0] in ctx.observed.registry_for(names[0])

    def execute(self, ctx: TargetContext) -> None:
        ctx.app.open_direct_messages(ctx.selected_targets[0])


class CopyCommand(ViewCommand, declared_name="copy"):
    help = "Copy name"

    def available(self, ctx: TargetContext) -> bool:
        return True

    def execute(self, ctx: TargetContext) -> None:
        ctx.app.copy_to_clipboard("\n".join(ctx.selected_targets))


class SortMembersCommand(SortCapable, ViewCommand, declared_name="sort"):
    help = "Sort members"

    def available(self, ctx: TargetContext) -> bool:
        names = ctx.selected_targets
        return len(names) == 1 and self.available_for_channel(names[0], ctx)

    def execute(self, ctx: TargetContext) -> None:
        self.execute_sort(ctx.selected_targets[0], ctx)

    def available_for_channel(self, channel: str, ctx) -> bool:
        return channel in ctx.app.workspace_chrome.channels.roster.groups

    def execute_sort(self, channel: str, ctx) -> None:
        group = ctx.app.workspace_chrome.channels.roster.groups[channel]
        ctx.app.run_worker(group.sort_choice.open_sort(), group="sort-order")


class CloseViewCommand(ViewCommand, declared_name="close_view"):
    help = "Close view"

    def available(self, ctx: TargetContext) -> bool:
        return (
            not ctx.targets
            and ctx.mode is not None
            and ctx.app.has_session(ctx.mode)
        )

    def execute(self, ctx: TargetContext) -> None:
        ctx.app.close_session(ctx.mode)


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

    async def apply(self, conversation: ConversationCommands) -> bool:
        return await self.choice.apply(conversation, self.context)
