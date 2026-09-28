"""One contextual command projection for pointer menus and slash discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Self

from agent_comms.comms import Comms
from toad import messages
from toad.comms_root import implicit_root, root_is_current, run_selected_write
from toad.slash_command import LocalCommand, SlashCommand
from toad.thread_actions import AcknowledgeAction, ThreadAction

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
    is_thread: bool = True

    def candidates(self):
        return [ThreadCommand(action) for action in ThreadAction.menu()] + [
            member() for member in SlashCommand.members_with(TargetLocal)
        ]

    def current(self) -> TargetContext:
        if not root_is_current(self.comms.root):
            raise ValueError("Comms route changed; reopen this view")
        return self

    def thread(self):
        return self.comms.registry.require(self.subject)

    def channel_view(self):
        return self.comms.channels.catalog.read().resolve(self.channel or self.subject)


class ContextualCommand(ABC):
    command: str

    @abstractmethod
    def available(self, ctx: TargetContext) -> bool: ...

    @abstractmethod
    def label(self, ctx: TargetContext) -> str: ...

    @abstractmethod
    def execute(self, ctx: TargetContext) -> None: ...

    def parse_arguments(self, arguments: str) -> ContextualCommand:
        if arguments.strip():
            raise ValueError(
                "Use the current target; fork parameters are collected in its dialog"
            )
        return self

    def target_context(self, ctx: TargetContext) -> TargetContext:
        return ctx

    async def run(self, conversation: Conversation) -> bool:
        ctx = conversation.command_target_context()
        if ctx is None:
            raise ValueError("No current target for this command")
        ctx = self.target_context(ctx).current()
        if not self.available(ctx):
            raise ValueError("Action is no longer available for this target")
        self.execute(ctx)
        conversation.update_slash_commands()
        return True


@dataclass(frozen=True)
class ThreadCommand(ContextualCommand):
    action: type[ThreadAction]

    @property
    def command(self) -> str:
        return f"/{self.action.declared_name}"

    def available(self, ctx: TargetContext) -> bool:
        if not ctx.is_thread:
            return self.action is AcknowledgeAction
        thread = ctx.thread()
        return self.action.available(ctx.comms.registry.status(ctx.subject), thread.pid)

    def label(self, ctx: TargetContext) -> str:
        return self.action.menu_label()

    def execute(self, ctx: TargetContext) -> None:
        ctx.current()
        if not self.available(ctx):
            raise ValueError("Action is no longer available for this target")
        modes = (ctx.mode,) if ctx.mode is not None else ()
        self.action.request(ctx.app, ctx.subject, ctx.actor, modes)


class TargetLocal:
    """Context-dependent interface actions, derived from their declarations."""


class ViewCommand(ContextualCommand, SlashCommand, LocalCommand, TargetLocal):
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
        ctx.app.post_message(messages.SessionArchive(ctx.mode))


@dataclass(frozen=True)
class PinCommand(ViewCommand, declared_name="pin"):
    help = "Toggle pin"
    hint = "<optional @member of this channel>"
    member: str | None = None

    @classmethod
    def parse(cls, arguments: str) -> Self:
        values = arguments.split()
        if len(values) > 1:
            raise ValueError("Expected one channel member")
        return cls(values[0].removeprefix("@") if values else None)

    def parse_arguments(self, arguments: str) -> PinCommand:
        return type(self).parse(arguments)

    def target_context(self, ctx: TargetContext) -> TargetContext:
        if self.member is None:
            return ctx
        if ctx.is_thread:
            raise ValueError("Select a channel before specifying a member to pin")
        return replace(
            ctx, subject=self.member, channel=ctx.subject, mode=None, is_thread=True
        )

    def available(self, ctx: TargetContext) -> bool:
        return not ctx.is_thread or (
            ctx.channel is not None and ctx.channel_view().matches(ctx.thread().tags)
        )

    def label(self, ctx: TargetContext) -> str:
        view = ctx.channel_view()
        if ctx.is_thread:
            pinned = ctx.subject in ctx.comms.channels.catalog.read().pinned_threads(
                ctx.channel
            )
            return "Unpin from this channel" if pinned else "Pin in this channel"
        return "Unpin channel" if view.pinned else "Pin channel"

    def execute(self, ctx: TargetContext) -> None:
        view = ctx.channel_view()
        if ctx.is_thread:
            run_selected_write(
                ctx.comms.root,
                ctx.comms.channels.set_thread_pinned,
                ctx.channel,
                ctx.subject,
                ctx.subject
                not in ctx.comms.channels.catalog.read().pinned_threads(ctx.channel),
                implicit=implicit_root(),
            )
        else:
            run_selected_write(
                ctx.comms.root,
                ctx.comms.channels.set_channel_pinned,
                ctx.subject,
                not view.pinned,
                implicit=implicit_root(),
            )


class AnyModeCommand(ViewCommand, declared_name="any_mode"):
    help = "Toggle member activity"

    def available(self, ctx: TargetContext) -> bool:
        return not ctx.is_thread and ctx.channel_view().exact

    def label(self, ctx: TargetContext) -> str:
        return (
            "Show channel only"
            if ctx.channel_view().any_mode
            else "Show member activity"
        )

    def execute(self, ctx: TargetContext) -> None:
        run_selected_write(
            ctx.comms.root,
            ctx.comms.channels.set_channel_any_mode,
            ctx.subject,
            not ctx.channel_view().any_mode,
            implicit=implicit_root(),
        )


def target_commands(ctx: TargetContext) -> tuple[ContextualCommand, ...]:
    ctx.current()
    return tuple(command for command in ctx.candidates() if command.available(ctx))


@dataclass(frozen=True)
class TargetSuggestion(SlashCommand):
    choice: ContextualCommand
    help: str
    hint = None

    @property
    def command(self) -> str:
        return self.choice.command

    @classmethod
    def parse(cls, arguments: str) -> Self:
        raise ValueError("Target suggestions are projections of existing declarations")

    def parse_arguments(self, arguments: str) -> Self:
        return type(self)(self.choice.parse_arguments(arguments), self.help)

    async def run(self, conversation: Conversation) -> bool:
        return await self.choice.run(conversation)


def target_completion(ctx: TargetContext) -> list[SlashCommand]:
    return [
        TargetSuggestion(command, command.label(ctx))
        for command in target_commands(ctx)
    ]


class ViewContext(TargetContext):
    """A saved view has only view-local actions, never a guessed thread target."""

    def candidates(self):
        return [CloseViewCommand()]
