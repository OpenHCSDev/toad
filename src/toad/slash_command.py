"""Command declarations own completion, argument parsing and execution."""

from __future__ import annotations

import shlex
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Self

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.planning.command import Command
from agent_comms.planning.goal_actions import (
    ActiveGoalAction,
    ClearGoalAction,
    GoalAction,
    PausedGoalAction,
    RetryGoalAction,
    SetGoalAction,
)

from toad.client.commands import (
    AgentConversationCommands,
    AgentLocalCommand,
    CommandRefused,
    ConversationCommands,
    SharedTargetContext,
    ViewLocalCommand,
)
from toad.client.line_blocks import CommandRole, MutedRole, Span
from toad.twitter import tweet_intent_url


class CommandPresentation:
    """Completion text and argument decoding shared by command declarations."""

    @property
    def name_span(self) -> Span:
        return Span(self.command, CommandRole)

    @property
    def help_span(self) -> Span:
        return Span(self.help, MutedRole)

    def __str__(self) -> str:
        return self.command

    def parse_arguments(self, arguments: str) -> SlashCommand:
        return type(self).parse(arguments)

    def completion(self, context: SharedTargetContext | None):
        return (self,)

    def target_choices(self, context: SharedTargetContext | None):
        return ()

    def highlight_input(self, text: str, arguments_started: bool) -> tuple[Span, ...]:
        if not arguments_started:
            return (Span(text),)
        spans = (self.name_span, Span(text[len(self.command):]))
        if text == self.command + " " and self.hint:
            return (*spans, Span(self.hint, MutedRole))
        return spans



class SlashCommand(CommandPresentation, Command, DeclaredFamily, affix="Command"):
    help: ClassVar[str]
    hint: ClassVar[str | None] = None
    requires_agent: ClassVar[bool] = False

    @property
    def command(self) -> str:
        return f"/{self.declared_name}"



    @classmethod
    @abstractmethod
    def parse(cls, arguments: str) -> Self:
        """Decode command arguments once."""






@dataclass(frozen=True)
class AgentAdvertisedCommand(SlashCommand):
    requires_agent: ClassVar[bool] = True
    name: str
    help: str
    hint: str | None = None

    @property
    def command(self) -> str:
        return f"/{self.name}"

    @classmethod
    def from_acp(cls, record) -> Self:
        return cls(record.name, record.description, record.input.root.hint if record.input else None)

    @classmethod
    def parse(cls, arguments: str) -> Self:
        raise ValueError("Advertised commands are decoded at the ACP boundary")

    def parse_arguments(self, arguments: str) -> Self:
        # The submission still owns the complete original text and arguments.
        return self

    async def apply(self, conversation: ConversationCommands) -> bool:
        return False


class NoArgumentsCommand(SlashCommand):
    @classmethod
    def parse(cls, arguments: str) -> Self:
        return cls()


@dataclass(frozen=True)
class TeamCommand(SlashCommand, ViewLocalCommand):
    help = "Open the live team HUD"
    hint = "[teammate]"
    teammate: str = ""

    @classmethod
    def parse(cls, arguments: str) -> Self:
        names = shlex.split(arguments)
        if len(names) > 1:
            raise CommandRefused("Use /team [teammate].")
        return cls(*names)

    async def apply(self, conversation: ConversationCommands) -> bool:
        conversation.open_team(self.teammate)
        return True


class LoginCommand(NoArgumentsCommand, AgentLocalCommand):
    help = "Connect a provider using the agent's native login UI"

    async def apply(self, conversation: AgentConversationCommands) -> bool:
        conversation.provider_login()
        return True


@dataclass(frozen=True)
class ProjectCommand(SlashCommand, AgentLocalCommand):
    help = "Change this thread's project directory"
    hint = "<directory>"
    path: Path | None = None

    @classmethod
    def parse(cls, arguments: str) -> Self:
        path = arguments.strip()
        if path.startswith(("'", '"')):
            values = shlex.split(path)
            if len(values) != 1:
                raise CommandRefused("Expected one project directory")
            path = values[0]
        return cls(Path(path) if path else None)

    async def apply(self, conversation: AgentConversationCommands) -> bool:
        if self.path is None:
            conversation.flash(f"Project: {conversation.project_path}")
        else:
            await conversation.change_project(self.path)
        return True


class GoalControl(DeclaredFamily, affix="Control"):
    action: ClassVar[type[GoalAction]]


class PauseControl(GoalControl):
    action = PausedGoalAction


class ResumeControl(GoalControl):
    action = ActiveGoalAction


class RetryControl(GoalControl):
    action = RetryGoalAction


class ClearControl(GoalControl):
    action = ClearGoalAction


@dataclass(frozen=True)
class GoalCommand(SlashCommand, AgentLocalCommand):
    help = "Set or manage a persistent thread goal"
    objective: str = ""
    control: type[GoalControl] | None = None

    @property
    def hint(self) -> str:
        return "<objective | " + " | ".join(GoalControl.names()) + ">"

    @classmethod
    def parse(cls, arguments: str) -> Self:
        text = arguments.strip()
        try:
            control = GoalControl.member_named(text)
        except ValueError:
            return cls(text)
        return cls(control=control)

    async def apply(self, conversation: AgentConversationCommands) -> bool:
        if self.control is not None:
            await conversation.change_goal(self.control.action)
        elif self.objective:
            await conversation.change_goal(SetGoalAction, self.objective)
        else:
            await conversation.refresh_goal()
            conversation.flash(
                f"Use /goal {self.hint} to set, edit or manage this thread's goal."
            )
        return True


@dataclass(frozen=True)
class CompactCommand(SlashCommand, AgentLocalCommand):
    help = "Compact this thread's model context"
    hint = "<optional summary instructions>"
    instructions: str | None = None

    @classmethod
    def parse(cls, arguments: str) -> Self:
        return cls(arguments.strip() or None)

    async def apply(self, conversation: AgentConversationCommands) -> bool:
        if not conversation.can_compact:
            conversation.flash_error("Wait for the current response before compacting")
        else:
            conversation.request_compaction(self.instructions)
        return True


class ModelCommand(NoArgumentsCommand, AgentLocalCommand):
    help = "Choose this thread's model"

    async def apply(self, conversation: AgentConversationCommands) -> bool:
        conversation.focus_model_choice()
        return True


class AboutCommand(NoArgumentsCommand, ViewLocalCommand, declared_name="toad:about"):
    help = "About Toad"

    async def apply(self, conversation: ConversationCommands) -> bool:
        markdown = conversation.about_markdown()
        await conversation.post_markdown(markdown)
        conversation.app.copy_to_clipboard(markdown)
        conversation.app.show_info("A copy of /toad:about has been placed in your clipboard", self.command)
        return True


@dataclass(frozen=True)
class ClearCommand(SlashCommand, ViewLocalCommand, declared_name="toad:clear"):
    help = "Clear conversation window"
    hint = "<optional number of lines to preserve>"
    line_count: int = 0

    @classmethod
    def parse(cls, arguments: str) -> Self:
        try:
            return cls(max(0, int(arguments) if arguments.strip() else 0))
        except ValueError:
            raise CommandRefused("Unable to clear—a number was expected") from None

    async def apply(self, conversation: ConversationCommands) -> bool:
        await conversation.prune_window(self.line_count, self.line_count)
        return True


@dataclass(frozen=True)
class RenameCommand(SlashCommand, AgentLocalCommand, declared_name="toad:rename"):
    help = "Give the current session a friendly name"
    hint = "<session name>"
    name: str = ""

    @classmethod
    def parse(cls, arguments: str) -> Self:
        name = arguments.strip()
        if not name:
            raise CommandRefused(
                'Expected a name for the session. For example: "add comments to blog"'
            )
        return cls(name)

    async def apply(self, conversation: AgentConversationCommands) -> bool:
        await conversation.rename_session(self.name)
        conversation.flash_success(f"Renamed session to '{self.name}'")
        return True


class SessionCloseCommand(NoArgumentsCommand, AgentLocalCommand, declared_name="toad:session-close"):
    help = "Close the current session"

    async def apply(self, conversation: AgentConversationCommands) -> bool:
        if conversation.turn_busy:
            await conversation.cancel_agent()
        conversation.close_session()
        return True


@dataclass(frozen=True)
class SessionNewCommand(SlashCommand, AgentLocalCommand, declared_name="toad:session-new"):
    help = "Open a new session in the current working directory"
    hint = "<initial prompt or command>"
    prompt: str = ""

    @classmethod
    def parse(cls, arguments: str) -> Self:
        return cls(arguments.strip())

    async def apply(self, conversation: AgentConversationCommands) -> bool:
        conversation.request_new_session(self.prompt)
        return True


@dataclass(frozen=True)
class TestimonialCommand(SlashCommand, AgentLocalCommand, declared_name="toad:testimonial"):
    help = "Tweet a testimonial regarding Toad"
    hint = "<what you think of toad>"
    text: str = ""

    @classmethod
    def parse(cls, arguments: str) -> Self:
        return cls(arguments)

    async def apply(self, conversation: AgentConversationCommands) -> bool:
        default = (
            f"I'm running {conversation.agent_title} in the terminal with Toad."
            if conversation.agent_title is not None
            else "Try Toad, the universal interface for AI in your terminal"
        )
        conversation.app.open_url(tweet_intent_url(
            self.text or default,
            url="https://github.com/textualize/toad",
            via="willmcgugan",
            hashtags=["ai"],
        ))
        return True
