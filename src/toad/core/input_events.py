"""Original input/configuration requests, independent of their native editor."""

from dataclasses import dataclass
from typing import Literal

from agent_comms.messaging.message_files import FileUpload

from toad.core.link_context_changed import CoreEvent
from toad.goal_controls import GoalInteraction
from toad.input_history import InputHistory, PromptInputHistory, ShellInputHistory


@dataclass(frozen=True)
class HistoryMove(CoreEvent):
    direction: Literal[-1, +1]
    history_kind: type[InputHistory]
    body: str

    @classmethod
    def for_mode(cls, direction, shell: bool, body: str):
        return cls(direction, ShellInputHistory if shell else PromptInputHistory, body)


@dataclass(frozen=True)
class UserInputSubmitted(CoreEvent):
    """Editor submission options, before accepting input or sending it to the agent."""

    body: str
    shell: bool = False
    auto_complete: bool = False
    immediate: bool = False
    files: tuple[FileUpload, ...] = ()
    """What the message composer attached; an agent prompt attaches none."""


@dataclass(frozen=True)
class ChangeMode(CoreEvent):
    mode_id: str | None


@dataclass(frozen=True)
class ProviderLogin(CoreEvent):
    """Request the existing configured provider-authentication controls."""


@dataclass(frozen=True)
class ProjectDirectoryUpdated(CoreEvent):
    """The original filesystem watcher invalidated its project presentation."""


@dataclass(frozen=True)
class ChangeDirectory(CoreEvent):
    path: str


@dataclass(frozen=True)
class SelectHistoricalIdentity(CoreEvent):
    name: str
    source: str


@dataclass(frozen=True)
class GoalControlActivated(CoreEvent):
    action: type[GoalInteraction]
