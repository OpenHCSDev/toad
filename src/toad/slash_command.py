"""Command declarations own completion, argument parsing and execution."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Self
import shlex
from pathlib import Path

from agent_comms.command import Command
from agent_comms.declared_family import DeclaredFamily
from agent_comms.goal_actions import (
    ActiveGoalAction,
    ClearGoalAction,
    GoalAction,
    PausedGoalAction,
    RetryGoalAction,
    SetGoalAction,
)
from textual.content import Content

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation


class LocalCommand:
    """Commands interpreted by the interface before model submission."""


class SlashCommand(Command, DeclaredFamily, affix="Command"):
    help: ClassVar[str]
    hint: ClassVar[str | None] = None
    requires_agent: ClassVar[bool] = False

    @property
    def command(self) -> str:
        return f"/{self.declared_name}"

    @property
    def content(self) -> Content:
        return Content.assemble(
            (self.command, "$text-success"), "\t", (self.help, "dim")
        )

    def __str__(self) -> str:
        return self.command

    @classmethod
    @abstractmethod
    def parse(cls, arguments: str) -> Self:
        """Decode command arguments once."""

    def parse_arguments(self, arguments: str) -> SlashCommand:
        return type(self).parse(arguments)



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
        inputs = record.get("input") or {}
        return cls(record["name"], record["description"], inputs.get("hint"))

    @classmethod
    def parse(cls, arguments: str) -> Self:
        raise ValueError("Advertised commands are decoded at the ACP boundary")

    async def apply(self, conversation: Conversation) -> bool:
        return False


class NoArgumentsCommand(SlashCommand, LocalCommand):
    @classmethod
    def parse(cls, arguments: str) -> Self:
        return cls()


class LoginCommand(NoArgumentsCommand):
    help = "Connect a provider using the agent's native login UI"

    async def apply(self, conversation: Conversation) -> bool:
        conversation.action_provider_login()
        return True


@dataclass(frozen=True)
class ProjectCommand(SlashCommand, LocalCommand):
    help = "Change this thread's project directory"
    hint = "<directory>"
    path: Path | None = None

    @classmethod
    def parse(cls, arguments: str) -> Self:
        path = arguments.strip()
        if path.startswith(("'", '"')):
            values = shlex.split(path)
            if len(values) != 1:
                raise ValueError("Expected one project directory")
            path = values[0]
        return cls(Path(path) if path else None)

    async def apply(self, conversation: Conversation) -> bool:
        if self.path is None:
            conversation.flash(Content(f"Project: {conversation.project_path}"))
        elif conversation.agent is None:
            conversation.flash(
                "Project changes require an agent-comms session", style="error"
            )
        else:
            project = await conversation.agent.update_project(str(self.path))
            conversation.flash(
                Content(f"Project changed to {project}"), style="success"
            )
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
class GoalCommand(SlashCommand, LocalCommand):
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
            control = GoalControl.decode(text)
        except ValueError:
            return cls(text)
        return cls(control=control)

    async def apply(self, conversation: Conversation) -> bool:
        if self.control is not None:
            await conversation.change_goal(self.control.action.declared_name)
        elif self.objective:
            await conversation.change_goal(SetGoalAction.declared_name, self.objective)
        else:
            await conversation.refresh_goal()
            conversation.flash(
                f"Use /goal {self.hint} to set, edit or manage this thread's goal."
            )
        return True


@dataclass(frozen=True)
class CompactCommand(SlashCommand, LocalCommand):
    help = "Compact this thread's model context"
    hint = "<optional summary instructions>"
    instructions: str | None = None

    @classmethod
    def parse(cls, arguments: str) -> Self:
        return cls(arguments.strip() or None)

    async def apply(self, conversation: Conversation) -> bool:
        if conversation._compacting:
            conversation.flash("Context compaction is already running")
        elif conversation.turn == "agent":
            conversation.flash(
                "Wait for the current response before compacting", style="error"
            )
        elif conversation.agent is None:
            conversation.flash(
                "Context compaction requires an agent-comms session", style="error"
            )
        else:
            conversation._compacting = True
            conversation.compact_context(self.instructions)
        return True


class ModelCommand(NoArgumentsCommand):
    help = "Choose this thread's model"

    async def apply(self, conversation: Conversation) -> bool:
        if conversation.models:
            conversation.prompt.model_switcher.focus()
        else:
            conversation.flash("This agent has no model selector", style="error")
        return True


class AboutCommand(NoArgumentsCommand, declared_name="toad:about"):
    help = "About Toad"

    async def apply(self, conversation: Conversation) -> bool:
        from toad import about
        from toad.widgets.markdown_note import MarkdownNote

        markdown = about.render(conversation.app)
        await conversation.post(MarkdownNote(markdown, classes="about"))
        conversation.app.copy_to_clipboard(markdown)
        conversation.notify(
            "A copy of /toad:about has been placed in your clipboard",
            title=self.command,
        )
        return True


@dataclass(frozen=True)
class ClearCommand(SlashCommand, LocalCommand, declared_name="toad:clear"):
    help = "Clear conversation window"
    hint = "<optional number of lines to preserve>"
    line_count: int = 0

    @classmethod
    def parse(cls, arguments: str) -> Self:
        try:
            return cls(max(0, int(arguments) if arguments.strip() else 0))
        except ValueError:
            raise ValueError("Unable to clear—a number was expected") from None

    async def apply(self, conversation: Conversation) -> bool:
        await conversation.prune_window(self.line_count, self.line_count)
        return True


@dataclass(frozen=True)
class RenameCommand(SlashCommand, LocalCommand, declared_name="toad:rename"):
    help = "Give the current session a friendly name"
    hint = "<session name>"
    name: str = ""

    @classmethod
    def parse(cls, arguments: str) -> Self:
        name = arguments.strip()
        if not name:
            raise ValueError(
                'Expected a name for the session. For example: "add comments to blog"'
            )
        return cls(name)

    async def apply(self, conversation: Conversation) -> bool:
        await conversation.rename_session(self.name)
        conversation.flash(f"Renamed session to [b]'{self.name}'", style="success")
        return True


class SessionCloseCommand(NoArgumentsCommand, declared_name="toad:session-close"):
    help = "Close the current session"

    async def apply(self, conversation: Conversation) -> bool:
        from toad import messages

        if conversation.turn == "agent" and conversation.agent is not None:
            await conversation.agent.cancel()
        if conversation.screen.id is not None:
            conversation.post_message(messages.SessionClose(conversation.screen.id))
        return True


@dataclass(frozen=True)
class SessionNewCommand(SlashCommand, LocalCommand, declared_name="toad:session-new"):
    help = "Open a new session in the current working directory"
    hint = "<initial prompt or command>"
    prompt: str = ""

    @classmethod
    def parse(cls, arguments: str) -> Self:
        return cls(arguments.strip())

    async def apply(self, conversation: Conversation) -> bool:
        from toad import messages

        if conversation._agent_data is not None:
            conversation.post_message(
                messages.SessionNew(
                    conversation.working_directory,
                    conversation._agent_data["identity"],
                    self.prompt,
                )
            )
        return True


@dataclass(frozen=True)
class TestimonialCommand(SlashCommand, LocalCommand, declared_name="toad:testimonial"):
    help = "Tweet a testimonial regarding Toad"
    hint = "<what you think of toad>"
    text: str = ""

    @classmethod
    def parse(cls, arguments: str) -> Self:
        return cls(arguments)

    async def apply(self, conversation: Conversation) -> bool:
        from toad.twitter import open_tweet_intent

        default = (
            f"I'm running {conversation.agent_title} in the terminal with Toad."
            if conversation.agent_title is not None
            else "Try Toad, the universal interface for AI in your terminal"
        )
        open_tweet_intent(
            self.text or default,
            url="https://github.com/textualize/toad",
            via="willmcgugan",
            hashtags=["ai"],
        )
        return True
