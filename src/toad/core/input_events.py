"""Original input/configuration requests, independent of their native editor."""

from dataclasses import dataclass
from typing import Literal

from toad.input_history import InputHistory
from .events import CoreEvent


@dataclass(frozen=True)
class HistoryMove(CoreEvent):
    direction: Literal[-1, +1]
    history_kind: type[InputHistory]
    body: str

    @classmethod
    def for_mode(cls, direction, shell: bool, body: str):
        from toad.input_history import PromptInputHistory, ShellInputHistory
        return cls(direction, ShellInputHistory if shell else PromptInputHistory, body)


@dataclass(frozen=True)
class UserInputSubmitted(CoreEvent):
    """Editor submission options, before producer admission or native delivery."""

    body: str
    shell: bool = False
    auto_complete: bool = False
    immediate: bool = False


@dataclass(frozen=True)
class ChangeMode(CoreEvent):
    mode_id: str | None


@dataclass(frozen=True)
class ChangeModel(CoreEvent):
    model_id: str


@dataclass(frozen=True)
class ProviderLogin(CoreEvent):
    """Request the existing configured provider-authentication controls."""


@dataclass(frozen=True)
class ProjectDirectoryUpdated(CoreEvent):
    """The original filesystem watcher invalidated its project presentation."""
