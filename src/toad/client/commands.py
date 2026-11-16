"""Shared command context, target actions and command discovery.

Native menu/dialog/clipboard operations stay on native members.
The shared contract owns target selection, command availability,
action state and the absent/held execution family.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from asyncio import CancelledError
from dataclasses import dataclass, field
from pathlib import Path

from agent_comms.cli_verbs.cli_command import TargetAction
from agent_comms.cli_verbs.target_fields import TargetField
from agent_comms.messaging.channel_targets import (
    ChannelSelection,
    CommandTarget,
    NoChannel,
)
from agent_comms.planning.goal_actions import GoalAction
from agent_comms.projects.checkouts import Checkout
from agent_comms.transport.request import CoreAccess
from metaclass_registry import AbstractHooksMeta

from toad.client.connection import Observing
from toad.client.host import CommsHost


class CommandContextChanged(CancelledError):
    """A command's captured target context is no longer current."""


@dataclass(frozen=True)
class SharedTargetContext:
    """The target a command operates on, typed against the shared host contract.

    Native TargetContext inherits this and adds menu/widget methods.
    """

    app: CommsHost
    observed: Observing
    subject: CommandTarget
    actor: str
    project: Checkout
    mode: str | None = None
    channel: ChannelSelection = field(default_factory=NoChannel)
    targets: tuple[CommandTarget, ...] = ()

    @property
    def selection(self) -> tuple[CommandTarget, ...]:
        return self.targets or (self.subject,)

    @property
    def selected_targets(self) -> tuple[str, ...]:
        return tuple(name for target in self.selection for name in target.destination_names)

    @property
    def title(self) -> str:
        names = self.selected_targets
        return ", ".join(names) if names else str(self.project)


class SortCapable(ABC):
    """Capability mixin for commands that can sort channel members.
    The shared command checks availability; the native member implements
    the sort dialog through its framework's widgets."""

    @abstractmethod
    def available_for_channel(self, channel: str, ctx: SharedTargetContext) -> bool: ...

    @abstractmethod
    def execute_sort(self, channel: str, ctx: SharedTargetContext) -> None: ...


class ConversationCommands(metaclass=AbstractHooksMeta):
    """What a command does to the conversation it runs in.

    Commands call only these; each frontend's conversation inherits this and
    owns how each one happens on screen.
    """

    project_path: Checkout

    @abstractmethod
    async def command_target_context(self) -> SharedTargetContext | None: ...

    @abstractmethod
    def update_slash_commands(self) -> None: ...

    @property
    @abstractmethod
    def agent_title(self) -> str | None:
        """The connected agent's name, if one is connected."""

    @property
    @abstractmethod
    def can_compact(self) -> bool:
        """Whether the current turn allows compacting the model context now."""

    @property
    @abstractmethod
    def turn_busy(self) -> bool:
        """Whether an agent turn is running."""

    @abstractmethod
    def flash(self, text: str) -> None:
        """Show a short notice under the prompt."""

    @abstractmethod
    def flash_success(self, text: str) -> None: ...

    @abstractmethod
    def flash_error(self, text: str) -> None: ...

    @abstractmethod
    def notify(self, message: str, *, title: str = "") -> None:
        """Show a notification outside the conversation."""

    @abstractmethod
    def copy_to_clipboard(self, text: str) -> None: ...

    @abstractmethod
    def open_url(self, url: str) -> None: ...

    @abstractmethod
    def open_team(self, teammate: str) -> None:
        """Open the live team view, on one teammate when named."""

    @abstractmethod
    def focus_model_choice(self) -> None:
        """Move focus to this thread's model chooser."""

    @abstractmethod
    def provider_login(self) -> object:
        """Start the agent's own provider login."""

    @abstractmethod
    async def change_project(self, path: Path) -> None: ...

    @abstractmethod
    async def change_goal(self, action: type[GoalAction], text: str = "") -> None: ...

    @abstractmethod
    async def refresh_goal(self) -> None: ...

    @abstractmethod
    def request_compaction(self, instructions: str | None) -> None: ...

    @abstractmethod
    def about_markdown(self) -> str:
        """The /toad:about report for this installation and its Core."""

    @abstractmethod
    async def post_markdown(self, markdown: str) -> None:
        """Add a Markdown note to the conversation."""

    @abstractmethod
    async def prune_window(self, low_mark: int, high_mark: int) -> None: ...

    @abstractmethod
    async def rename_session(self, name: str) -> None: ...

    @abstractmethod
    async def cancel_agent(self) -> None:
        """Ask the agent to stop its running turn."""

    @abstractmethod
    def close_session(self) -> None:
        """Close the session this conversation shows."""

    @abstractmethod
    def request_new_session(self, prompt: str) -> None:
        """Open a new session in this conversation's working directory."""


class SharedContextualCommand(ABC):
    """A command available for a target context. Native commands inherit this
    alongside their framework's command registration (SlashCommand, etc.)."""

    command: str

    @abstractmethod
    def available(self, ctx: SharedTargetContext) -> bool: ...

    @abstractmethod
    def label(self, ctx: SharedTargetContext) -> str: ...

    @abstractmethod
    def execute(self, ctx: SharedTargetContext) -> None: ...

    async def apply(self, conversation: ConversationCommands, ctx: SharedTargetContext) -> bool:
        if await conversation.command_target_context() != ctx:
            raise CommandContextChanged("Command target changed; refresh this view")
        if not self.available(ctx):
            raise ValueError("Action is no longer available for this target")
        self.execute(ctx)
        conversation.update_slash_commands()
        return True


class TargetActionState(ABC):
    """Whether a thread has a pending target action. The family's absent
    member is NoTargetAction; the active member is ThreadActionExecution."""

    @property
    @abstractmethod
    def is_pending(self) -> bool: ...

    @abstractmethod
    def summary(self, row: object) -> str:
        """Status text for a sidebar row. The absent member uses the row's
        own summary; the active member uses the action's pending text."""

    @abstractmethod
    def busy(self, row: object) -> bool:
        """Whether the sidebar row shows busy state."""


class NoTargetAction(TargetActionState):
    """No pending action for this thread. One lookup, no reconstruction."""

    @property
    def is_pending(self) -> bool:
        return False

    def summary(self, row: object) -> str:
        return getattr(row, "summary", "")

    def busy(self, row: object) -> bool:
        return getattr(row, "working", False)


class CommandOrigin(ABC):
    """Captured native presentation owner for off-loop command preparation.

    Captured before the preparation worker starts. current() answers
    whether the view/screen is still selected and live when the reply
    arrives. edit() runs the native dialog, returning the argument
    mapping or None on cancellation.
    """

    @abstractmethod
    def current(self) -> bool:
        """Whether the captured view/screen is still selected and live."""

    @abstractmethod
    async def edit(self, definition: TargetAction, title: str, fields: tuple[TargetField, ...],
                   core: CoreAccess) -> dict[str, str | None] | None:
        """Run the native dialog. Returns arguments or None on cancel."""
