"""One contextual command projection for pointer menus and slash discovery."""

from __future__ import annotations
from toad.core import session_requests

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from functools import partial
from typing import TYPE_CHECKING, Self

from agent_comms.comms import Comms
from agent_comms.declared_family import DeclaredFamily
from toad import messages
from toad.comms_root import implicit_root, root_is_current, run_selected_write
from toad.slash_command import CommandPresentation, LocalCommand, SlashCommand
from toad.thread_actions import ChannelAction, ThreadAction

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.widgets.conversation import Conversation


class PinTarget(ABC):
    """Pin behavior is a target capability, not an action's type switch."""

    @abstractmethod
    def pin_target(self, member: str | None): ...

    @abstractmethod
    def can_pin(self) -> bool: ...

    @abstractmethod
    def pin_label(self) -> str: ...

    @abstractmethod
    def toggle_pin(self) -> None: ...


@dataclass(frozen=True)
class TargetContext(PinTarget, DeclaredFamily, affix="Context"):
    app: ToadApp
    comms: Comms
    subject: str
    actor: str
    project: Path
    mode: str | None = None

    def current(self) -> TargetContext:
        if not root_is_current(self.comms.root):
            raise ValueError("Comms route changed; reopen this view")
        return self

    @abstractmethod
    def can_run(self, action: type[ThreadAction]) -> bool: ...

    def available_actions(self) -> tuple[type[ThreadAction], ...]:
        return tuple(action for action in ThreadAction.menu() if self.can_run(action))

    def activity_available(self) -> bool:
        return False

    def show_menu(self, sidebar, offset) -> None:
        from toad.widgets.comms_menu import show_target_menu
        choices = self.command_choices()
        show_target_menu(sidebar.app.screen, offset, self.subject,
            [(command.command.removeprefix("/"), command.label(self)) for command in choices],
            {command.command.removeprefix("/"): partial(self.execute_menu, sidebar, command)
             for command in choices})

    def command_choices(self):
        from toad.command_catalog import CommandCatalog
        return CommandCatalog((), self).target_choices

    def execute_menu(self, sidebar, command) -> None:
        try:
            self.current()
            if not command.available(self):
                raise ValueError("Action is no longer available for this target")
            command.execute(self)
            sidebar.observation.refresh()
        except (OSError, ValueError) as error:
            sidebar.notify(str(error), title="Target action", severity="error")


@dataclass(frozen=True)
class ThreadContext(TargetContext, declared_name="dm"):
    channel: str | None = None

    def thread(self):
        return self.comms.registry.require(self.subject)

    def can_run(self, action: type[ThreadAction]) -> bool:
        return action.available(self.thread(), self.comms.registry.status(self.subject))

    def available_actions(self) -> tuple[type[ThreadAction], ...]:
        snapshot = self.comms.registry.snapshot()
        name = snapshot.aliases.get(self.subject, self.subject)
        thread = snapshot.threads[name]
        return ThreadAction.available_menu(thread, snapshot.statuses[name])

    def pin_target(self, member: str | None) -> ThreadContext:
        if member is not None:
            raise ValueError("Select a channel before specifying a member to pin")
        return self

    def can_pin(self) -> bool:
        return self.channel is not None and self.comms.channels.catalog.read().resolve(
            self.channel).matches(self.thread().tags)

    def pin_label(self) -> str:
        pinned = self.subject in self.comms.channels.catalog.read().pinned_threads(self.channel)
        return "Unpin from this channel" if pinned else "Pin in this channel"

    def toggle_pin(self) -> None:
        run_selected_write(self.comms.root, self.comms.channels.set_thread_pinned,
            self.channel, self.subject,
            self.subject not in self.comms.channels.catalog.read().pinned_threads(self.channel),
            implicit=implicit_root())


class ChannelContext(TargetContext, declared_name="channel"):
    def channel_view(self):
        return self.comms.channels.catalog.read().resolve(self.subject)

    def can_run(self, action: type[ThreadAction]) -> bool:
        return issubclass(action, ChannelAction)

    def pin_target(self, member: str | None) -> TargetContext:
        if member is None:
            return self
        return ThreadContext(self.app, self.comms, member, self.actor, self.project,
                             channel=self.subject)

    def can_pin(self) -> bool:
        return self.channel_view().exact

    def pin_label(self) -> str:
        return "Unpin channel" if self.channel_view().pinned else "Pin channel"

    def toggle_pin(self) -> None:
        run_selected_write(self.comms.root, self.comms.channels.set_channel_pinned,
            self.subject, not self.channel_view().pinned, implicit=implicit_root())

    def activity_available(self) -> bool:
        return self.channel_view().exact


class FeedContext(ChannelContext, declared_name="irc"):
    """Aggregate history has no exact-channel pin or activity mutation."""


class ViewContext(TargetContext):
    """Saved view identity grants closing/copying, never thread/channel mutation."""

    def can_run(self, action: type[ThreadAction]) -> bool:
        return False

    def pin_target(self, member: str | None) -> ViewContext:
        if member is not None:
            raise ValueError("Saved views cannot select channel members")
        return self

    def can_pin(self) -> bool:
        return False

    def pin_label(self) -> str:
        raise ValueError("Saved views cannot be pinned as channels")

    def toggle_pin(self) -> None:
        raise ValueError("Saved views cannot be pinned as channels")


class ContextualCommand(CommandPresentation, ABC):
    command: str

    def target_choices(self, context: TargetContext | None, available_actions):
        return (self,) if context is not None and self.available(context) else ()

    def completion(self, context: TargetContext | None, available_actions):
        return tuple(TargetSuggestion(command, context)
                     for command in self.target_choices(context, available_actions))

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

    async def apply(self, conversation: Conversation) -> bool:
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

    def target_choices(self, context: TargetContext | None, available_actions):
        return (self,) if self.action in available_actions else ()

    @property
    def command(self) -> str:
        return f"/{self.action.declared_name}"

    def available(self, ctx: TargetContext) -> bool:
        return ctx.can_run(self.action)

    def label(self, ctx: TargetContext) -> str:
        return self.action.menu_label()

    def execute(self, ctx: TargetContext) -> None:
        ctx.current()
        if not self.available(ctx):
            raise ValueError("Action is no longer available for this target")
        modes = (ctx.mode,) if ctx.mode is not None else ()
        self.action.request(ctx.app, ctx.subject, ctx.actor, modes)


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
        return ctx.pin_target(self.member)

    def available(self, ctx: TargetContext) -> bool:
        return ctx.can_pin()

    def label(self, ctx: TargetContext) -> str:
        return ctx.pin_label()

    def execute(self, ctx: TargetContext) -> None:
        ctx.toggle_pin()


class AnyModeCommand(ViewCommand, declared_name="any_mode"):
    help = "Toggle member activity"

    def available(self, ctx: TargetContext) -> bool:
        return ctx.activity_available()

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
        return await self.choice.apply(conversation)
