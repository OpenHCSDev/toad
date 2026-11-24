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

from toad.agent_binding import AgentConnection, NoAgentConnection
from toad.client.category_selection import CategorySelection, NoCategorySelection
from toad.project_path_owner import CheckoutRoot
from toad.thread_identity import NoThreadIdentity, SessionIdentity, ThreadIdentity
from toad.transcript_scope import NoTranscript, TranscriptScope

if TYPE_CHECKING:
    from toad.client.conversation_sources import ConversationSources
    from toad.client.session_sources import MailboxSources


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
        """The session this view belongs to. A view of a conversation, a mailbox or an agent
        tab belongs to none, and says so by its mode; a session's own view is its origin."""
        return NoSessionOrigin(self.mode)

    @property
    def operational_binding(self):
        """The agent this session runs: a view with no agent (welcome, a channel, a CLI
        inbox) has none. Textual's `MainScreen` answers its presentation's binding, Qt's
        conversation views their `agent_binding`."""
        return NoAgentConnection()

    @property
    def category_selection(self) -> CategorySelection:
        """The categories this view's transcript shows. A view without a transcript filters
        nothing; a view that filters inherits `CategorySelection`, which answers itself."""
        return NoCategorySelection()

    _identity: SessionIdentity = NoThreadIdentity()

    @property
    def thread_identity(self) -> SessionIdentity:
        """Default for a view that has no thread (welcome, home). Views holding a
        thread bind `_identity` (or override this property)."""
        return self._identity

    @property
    def coordination_root(self) -> str | None:
        """The bus root this session's thread is read from; a view with no thread has none.
        Thread navigation asks every open session for it to find a tab already showing a
        thread, so every frontend's views answer it the same way."""
        return self.thread_identity.wire_root()

    @property
    def sidebar_thread_identity(self) -> object:
        return self.thread_identity

    def configuration_fields(self):
        """The settings this view's settings pane lists: none for a view without its own
        (the welcome, an opening view); a `ViewSettingsOwner` lists its configuration's."""
        return ()

    def close_configuration(self) -> None:
        """A view without its own settings holds no configuration to close."""

    def configuration_actions(self) -> tuple:
        """A view without a configurable subject offers no configuration operations."""
        return ()

    @property
    def bound_agent(self) -> AgentConnection:
        """The agent this view presents. A view with none (the welcome, a DM's
        `ConversationView`) answers `NoAgentConnection`, which has no plan and whose events
        never fire, so a panel reads the agent without testing for its absence. A view that
        binds an agent (`AgentBoundConversation`) overrides this with its binding."""
        return NoAgentConnection()

    def belongs_to_wire(self, root: Path) -> bool:
        raise NotImplementedError

    def matches_launch(self, agent_identity: str, session_id: AcpSessionId) -> bool:
        return False

    def apply_external_mailbox_sources(self) -> None:
        """`ExternalThreadNavigation.bind` calls this on the view it opens. A view that
        presents a conversation (`BoundSources`) takes its mailbox sources; a view with no
        sources (the welcome, an opening view) has none to change."""

    def apply_native_load_plan(self, plan) -> None:
        """`NativeThreadNavigation.bind` calls this on the view it opens. A view that presents
        a conversation (`BoundSources`) gives its sources the plan; a view with none keeps
        nothing."""

    async def wait_content_ready(self) -> None:
        """Opening a tab returns once its content has loaded. A view composed with its
        content, or one that draws it as it arrives, is ready once shown; a view that loads
        first waits here."""

    def close_core_events(self) -> None:
        """End the view's Core subscriptions before its tab entry is forgotten."""
        raise NotImplementedError

    async def retire_presentation(self) -> None:
        """Let go of what the view drew before the tab it returns to is shown. A view that
        keeps nothing beside the rows it shows has nothing to let go of."""


class BoundSources(SessionScope):
    """A view thread navigation binds: it holds the sources its conversation reads its queue
    and starts its submissions through, and the navigation's bind changes them. Both hooks
    are decided here, once. A frontend says only where the sources are kept
    (`operational_sources`: Textual's screen keeps them on its presentation, Qt's view on
    itself)."""

    operational_sources: ConversationSources

    def mailbox_sources(self) -> MailboxSources:
        """The sources of a thread whose input goes to Core's inbox. A frontend whose
        mailbox adds to them (Textual's, its prompt) answers its own."""
        from toad.client.session_sources import MailboxSources
        return MailboxSources()

    def apply_external_mailbox_sources(self) -> None:
        """The opened thread takes its input through Core's inbox, not an agent session."""
        self.operational_sources = self.mailbox_sources()

    def apply_native_load_plan(self, plan) -> None:
        """The opened thread's session resumes from `plan`."""
        self.operational_sources.load_plan = plan


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

    def opening_standing(self, selected_mode: str) -> str:
        """What must not change while a thread opened from here is prepared: a view opens
        what it was asked for only while it is still the tab shown."""
        return selected_mode


class HomeSessionOrigin(ProjectSessionOrigin):
    """Home, the welcome: every row and link opens from here whichever tab is shown
    (`TargetOpen`), so another tab being selected meanwhile, as a second tap's opening is,
    leaves its openings current. Textual's `WelcomeScreen` and Qt's `QtWelcomeOrigin`.

    Home acts as the reader, whose thread is the bus's user thread: a read of Core's whole
    registry, which over a remote connection is megabytes and seconds. It is read once, off
    the loop, before a target opens from here (`prepare_history_origin`), and kept; every
    answer after that (`navigation_context`, `ThreadOrigin.capture` and its re-check when
    the opening ends) reads the kept one. Qt's origin computed it on every read, on the GUI
    thread: opening a thread from the welcome held the loop for a registry read, twice
    (2026-11-22, a sampled stack of a long loop step)."""

    def read_history_identity(self, project) -> ThreadIdentity:
        """The reader's own thread on the bus observed now; blocks, so it runs on a worker."""
        observed = self.app.coordination_access.observation.observed()
        return ThreadIdentity(observed.user_identity(project).incarnation, str(observed.root))

    async def prepare_history_origin(self) -> None:
        identity = await self.app.preparation.run_thread(self.read_history_identity, self.project_path)
        self.home_identity_read(identity)

    def home_identity_read(self, identity: SessionIdentity) -> None:
        """The reader's thread was read: it is home's identity."""
        self._identity = identity

    def opening_standing(self, selected_mode: str) -> str:
        return ""


class NoConversationView(SessionScope):
    """The view the thread sidebar follows while no conversation is open: the welcome, as
    Textual's welcome is a `SessionScope` answering the defaults. Every answer a panel reads
    is this family's own absent member (`NoThreadIdentity`, `NoCategorySelection`,
    `NoAgentConnection`), so a binder takes a view and never tests for one."""

    @property
    def is_current(self) -> bool:
        return False
