"""Shared session scope: the logical answers every session view provides.

Native sessions compose this with their framework base (ToadNode for Textual,
QWidget for Qt). The shared contract owns identity, display, navigation and
source answers without importing any toolkit.
"""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Never

from agent_comms.errors import RelationViolationError
from agent_comms.nominal.field_codec import AcpSessionId
from metaclass_registry import AbstractHooksMeta

from toad.project_path_owner import CheckoutRoot
from toad.transcript_scope import NoTranscript, TranscriptScope


class SessionOrigin(metaclass=AbstractHooksMeta):
    """An origin answers for itself, including when its view is unavailable."""

    @abstractmethod
    def transcript_scope(self) -> TranscriptScope: ...

    @abstractmethod
    def require(self) -> ProjectSessionOrigin: ...


class NoSessionOrigin(SessionOrigin):
    def __init__(self, view: str = "unavailable view") -> None:
        self.view = view

    def transcript_scope(self) -> NoTranscript:
        return NoTranscript()

    def require(self) -> Never:
        raise RelationViolationError(f"View {self.view!r} has no session origin")


class SessionScope:
    """The logical session: identity, display name, navigation and source.

    A plain parent: ABCMeta would conflict with each toolkit's widget metaclass.

    Native subclasses add their framework base. Textual adds ToadNode,
    COMMANDS, sidebars, keyboard_scopes and _pre_process. Qt adds its
    QWidget and native lifecycle.
    """

    @property
    def is_current(self) -> bool:
        raise NotImplementedError

    @property
    def display_name(self) -> str:
        raise NotImplementedError

    @property
    def navigation_target(self) -> object:
        raise NotImplementedError

    @property
    def origin(self) -> SessionOrigin:
        raise NotImplementedError

    @property
    def thread_identity(self) -> object:
        raise NotImplementedError

    @property
    def sidebar_thread_identity(self) -> object:
        return self.thread_identity

    def belongs_to_wire(self, root: Path) -> bool:
        raise NotImplementedError

    def matches_launch(self, agent_identity: str, session_id: AcpSessionId) -> bool:
        return False

    async def wait_content_ready(self) -> None:
        """Opening a tab returns once its content has loaded."""
        raise NotImplementedError

    def close_core_events(self) -> None:
        """End the view's Core subscriptions before its tab entry is forgotten."""
        raise NotImplementedError

    async def retire_presentation(self) -> None:
        """Let go of what the view drew before the tab it returns to is shown."""
        raise NotImplementedError


class ProjectSessionOrigin(SessionOrigin, SessionScope, CheckoutRoot):
    """A project source may navigate without an ACP session."""

    async def prepare_history_origin(self) -> None:
        """An agent view already has its thread; resident views acquire theirs."""

    @property
    def origin(self) -> SessionOrigin:
        return self

    def transcript_scope(self) -> TranscriptScope:
        return self.thread_identity.transcript_scope()

    def require(self) -> ProjectSessionOrigin:
        return self

    def agent_for_opening[Binding](self, default: Binding) -> Binding:
        """A project origin with no launch of its own opens views with the app's binding."""
        return default
