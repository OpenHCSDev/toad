from dataclasses import dataclass

from typing import Literal

from textual.content import Content
from textual.widget import Widget
from textual.message import Message

from toad.session_tracker import SessionState


class WorkStarted(Message):
    """Work has started."""


class WorkFinished(Message):
    """Work has finished."""


@dataclass
class HistoryMove(Message):
    """Getting a new item form history."""

    direction: Literal[-1, +1]
    shell: bool
    body: str


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
class SessionNavigate(Message):
    """Request to switch session."""

    mode_name: str
    direction: Literal[-1, +1]


@dataclass
class SessionSwitch(Message):
    """Switch to specified session."""

    mode_name: str


@dataclass
class SessionNew(Message):
    """Open a new session."""

    path: str
    """project directory path."""
    agent: str
    """Agent identity."""
    prompt: str
    """Initial prompt or command"""


@dataclass
class SessionCreate(Message):
    """Create another session with the app's configured agent and project."""

    source_mode: str


@dataclass
class SessionRename(Message):
    mode_name: str
    name: str


@dataclass
class SessionArchive(Message):
    mode_name: str


@dataclass
class SessionDelete(Message):
    mode_name: str


@dataclass
class SessionUpdate(Message):
    name: str | None = None
    """Name of the session, or `None` for no change."""
    subtitle: str | None = None
    """Session subtitle (name of agent)."""
    path: str | None = None
    """Project directory path."""
    state: SessionState | None = None
    """New session state."""
    summary: str | None = None
    """Current agent activity shown in session lists."""


@dataclass
class SessionClose(Message):
    name: str
    """Name of the session."""


@dataclass
class LaunchAgent(Message):
    """Inform app to launch agent."""

    identity: str
    session_id: str | None = None
    pk: int | None = None
    prompt: str | None = None
