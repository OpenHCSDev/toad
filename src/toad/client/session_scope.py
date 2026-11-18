"""Shared session scope: the logical answers every session view provides.

Native sessions compose this with their framework base (ToadNode for Textual,
QWidget for Qt). The shared contract owns identity, display, navigation and
source answers without importing any toolkit.
"""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Never

from agent_comms.errors import RelationViolationError
from agent_comms.nominal.field_codec import AcpSessionId
from metaclass_registry import AbstractHooksMeta

from toad.project_path_owner import CheckoutRoot
from toad.transcript_scope import NoTranscript, TranscriptScope

if TYPE_CHECKING:
    from toad.agent_binding import AgentConnection
    from toad.client.category_selection import CategorySelection


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
    def category_selection(self) -> CategorySelection:
        """The categories this view's transcript shows. A view without a transcript filters
        nothing; a view that filters inherits `CategorySelection`, which answers itself."""
        from toad.client.category_selection import NoCategorySelection
        return NoCategorySelection()

    @property
    def thread_identity(self) -> object:
        """Default for a view that has no thread (welcome, home). A view with a
        thread (ACP, conversation) overrides this to return its SessionIdentity.
        Returning a NoThreadIdentity instead of raising keeps generic sidebar /
        notification code — e.g. ThreadSettingsPane.bind — from having to guard
        every read with try/NotImplementedError, mirroring Textual's NoThreadIdentity default."""
        from toad.thread_identity import NoThreadIdentity
        return NoThreadIdentity()

    @property
    def sidebar_thread_identity(self) -> object:
        return self.thread_identity

    @property
    def bound_agent(self) -> AgentConnection:
        """The agent this view presents. A view with none (the welcome, a DM's
        `ConversationView`) answers `NoAgentConnection`, which has no plan and whose events
        never fire, so a panel reads the agent without testing for its absence. A view that
        binds an agent (`AgentBoundConversation`) overrides this with its binding."""
        from toad.agent_binding import NoAgentConnection
        return NoAgentConnection()

    def belongs_to_wire(self, root: Path) -> bool:
        raise NotImplementedError

    def matches_launch(self, agent_identity: str, session_id: AcpSessionId) -> bool:
        return False

    def apply_external_mailbox_sources(self) -> None:
        """`ExternalThreadNavigation.bind(screen)` calls this; Textual's MainScreen
        overrides to assign `self.presentation.sources = MailboxSessionSources()`
        (which drags in the whole Textual-widget pyramid: session_presentation →
        widgets.conversation → widgets.prompt → path_filter → pathspec). Qt views
        have no `presentation.sources` contract today, so the default is a no-op.
        Pushing the assignment into a polymorphic method keeps the import chain
        out of the Qt bind path — same pattern as `make_opening_view`."""

    def apply_native_load_plan(self, plan) -> None:
        """`NativeThreadNavigation.bind(screen)` calls this; Textual's MainScreen
        overrides to assign `self.presentation.sources.load_plan = plan`. Qt views
        have no sources container today, so the default is a no-op."""

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


class NoConversationView(SessionScope):
    """The view the thread sidebar follows while no conversation is open: the welcome, as
    Textual's welcome is a `SessionScope` answering the defaults. Every answer a panel reads
    is this family's own absent member (`NoThreadIdentity`, `NoCategorySelection`,
    `NoAgentConnection`), so a binder takes a view and never tests for one."""

    @property
    def is_current(self) -> bool:
        return False
