from dataclasses import dataclass

from typing import Literal

from textual.content import Content
from textual.widget import Widget
from textual.message import Message

from toad.input_history import InputHistory


class WorkStarted(Message):
    """Work has started."""


class WorkFinished(Message):
    """Work has finished."""


@dataclass
class HistoryMove(Message):
    """Getting a new item form history."""

    direction: Literal[-1, +1]
    history_kind: type[InputHistory]
    body: str

    @classmethod
    def for_mode(cls, direction, shell: bool, body: str):
        from toad.input_history import PromptInputHistory, ShellInputHistory
        return cls(direction, ShellInputHistory if shell else PromptInputHistory, body)


@dataclass
class UserInputSubmitted(Message):
    body: str
    shell: bool = False
    auto_complete: bool = False
    immediate: bool = False


class SendPromptNow(Message):
    pass


@dataclass
class PromptSuggestion(Message):
    suggestion: str


@dataclass
class Dismiss(Message):
    widget: Widget

    @property
    def control(self) -> Widget:
        return self.widget


@dataclass
class InsertPath(Message):
    path: str


@dataclass
class ChangeMode(Message):
    mode_id: str | None


@dataclass
class ChangeModel(Message):
    model_id: str


class ProviderLogin(Message):
    """Open the agent's advertised provider-authentication controls."""


@dataclass
class Flash(Message):
    """Request a message flash.

    Args:
        Message: Content of flash.
        style: Semantic style.
        duration: Duration in seconds or `None` for default.
    """

    content: str | Content
    style: Literal["default", "warning", "success", "error"]
    duration: float | None = None


class ProjectDirectoryUpdated(Message):
    """The project directory may may changed."""


@dataclass
class SessionUpdate(Message):
    name: str | None = None
    """Name of the session, or `None` for no change."""
    subtitle: str | None = None
    """Session subtitle (name of agent)."""
    path: str | None = None
    """Project directory path."""


