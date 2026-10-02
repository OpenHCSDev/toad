from dataclasses import dataclass

from typing import Literal

from textual.content import Content
from textual.widget import Widget
from textual.message import Message


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


@dataclass
class SessionUpdate(Message):
    name: str | None = None
    """Name of the session, or `None` for no change."""
    subtitle: str | None = None
    """Session subtitle (name of agent)."""
    path: str | None = None
    """Project directory path."""


