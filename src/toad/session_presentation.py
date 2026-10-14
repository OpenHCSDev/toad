"""Session-owned mounted presentation, with one bounded workspace admission owner."""

import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from toad.resource_release import AsyncResourceRelease
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from weakref import ref

from textual.widget import Widget
from textual.widgets.text_area import TextAreaState

from agent_comms.acp_extension import CoordinationChangedUpdate
from toad.owner_preparation import ExistingOwnerAdmission

from toad.input_history import InputHistories
from toad.agent_surface import AttachedSurfaceBinding
from toad.widgets.conversation import Conversation
from toad.widgets.history_anchor import ParkedPosition
from toad.widgets.message_filter import MessageCategory

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.screens.main import MainScreen


class SessionSurfaceSlot(Widget):
    """The session's stable placement for its admitted native presentation."""

    DEFAULT_CSS = "SessionSurfaceSlot { display: none; }"


@dataclass(frozen=True)
class SessionViewState:
    """The actual editor document/history and reader intent, not a transcript copy."""

    editor: TextAreaState
    visible_categories: frozenset[type[MessageCategory]]
    reader_position: ParkedPosition
    shell_mode: bool
    input_histories: InputHistories
    initial_prompt: str | None

    @classmethod
    def capture(cls, conversation: Conversation) -> "SessionViewState":
        editor = conversation.prompt.prompt_text_area
        return cls(
            editor.capture_editor_state(), conversation.visible_categories,
            conversation.window.park_reader(),
            editor.shell_mode, conversation.input_histories, conversation.take_initial_prompt(),
        )

    def prepare_transcript(self, conversation: Conversation) -> None:
        conversation.visible_categories = self.visible_categories
        conversation.window.reader_position = self.reader_position

    def restore(self, conversation: Conversation) -> None:
        conversation.input_histories = self.input_histories
        editor = conversation.prompt.prompt_text_area
        editor.restore_editor_state(self.editor)
        editor.shell_mode = self.shell_mode


class SessionSurfaceLifetime(ABC):
    """A session declares its own UI placement and activation lifetime."""

    @property
    def operational_agent(self):
        return None

    @abstractmethod
    def compose_content(self, screen: "MainScreen") -> Widget: ...

    @abstractmethod
    async def prepare(self, screen: "MainScreen") -> None: ...

    @abstractmethod
    async def retire(self, screen: "MainScreen") -> None: ...

    @abstractmethod
    async def close(self, screen: "MainScreen") -> None: ...


class EditorSessionSurfaceLifetime(SessionSurfaceLifetime):
    """Own retained editor state and active shell close semantics."""

    def __init__(self) -> None:
        self.state: SessionViewState | None = None

    @abstractmethod
    async def release_binding(self, conversation: Conversation, screen: "MainScreen") -> None: ...

    @abstractmethod
    async def attach_binding(self, conversation: Conversation) -> None: ...



class OperationalSessionSources:
    """Own existing operational resources while the view is detached."""

    def __init__(self) -> None:
        from agent_comms.session_load import EnsuringSessionLoadAdmission

        self.agent = None
        self.shell = None
        self.directory_watcher = None
        self.load_admission = EnsuringSessionLoadAdmission()

    def agent_info(self, conversation: Conversation) -> str:
        return "shell"

    def accepts_inbox_submission(self, event) -> bool:
        return False

    def input_ready(self, conversation: Conversation) -> bool:
        agent = conversation.agent
        if agent is None or not agent.ready:
            return False
        if conversation.transcript.readable:
            presentation = conversation.thread_presentation
            return (presentation is not None
                    and ExistingOwnerAdmission.from_binding(presentation.binding) is not None)
        return True

    def unavailable_reason(self, conversation: Conversation) -> str:
        presentation = conversation.thread_presentation
        if (conversation.transcript.readable and presentation is not None
                and ExistingOwnerAdmission.from_binding(presentation.binding) is None):
            return "Thread is stopped. Choose Start thread from its menu; your draft is kept."
        return "Agent is not ready. Please wait while the agent connects…"

    def start_agent(self, conversation: Conversation) -> None:
        """The operational source owns connection creation and load admission."""
        from toad.acp.agent import Agent
        from toad.core import events as core_events

        if conversation.agent is not None:
            return
        assert conversation._agent_data is not None
        agent = Agent(conversation.project_path, conversation._agent_data,
                      conversation._agent_session_id, conversation._session_pk)
        agent.session.load_admission = self.load_admission
        conversation.agent = agent
        conversation._native_agent_started_here = True
        conversation.bind_agent(agent)
        agent.controller.start_operation(agent.start(conversation.app.session_navigation.processes))
        conversation.publish_core(core_events.SessionSubtitleChanged(conversation.agent_title))

    def attach_started(self, screen: "MainScreen", admission) -> None:
        """An explicit Start action may attach the same retained view to its new owner."""
        self.load_admission = admission
        screen._agent = screen._agent or screen.app.agent_data
        conversation = screen.presentation.widget
        if conversation is not None:
            conversation._agent_data = screen._agent
            if screen.is_current:
                conversation.start_native_session()

    def wire(self, conversation: Conversation) -> None:
        if self.agent is not None:
            from toad.widgets.conversation import ConversationSessionBinding

            conversation.set_reactive(ConversationSessionBinding.agent, self.agent)
        watcher, self.directory_watcher = self.directory_watcher, None
        if watcher is not None:
            conversation._directory_watcher = watcher
            watcher.rebind(conversation)
            conversation.call_after_refresh(watcher.notify_if_visible)

    async def present(self, conversation: Conversation) -> None:
        shell, self.shell = self.shell, None
        if shell is not None:
            conversation._shell = shell
            await shell.attach(AttachedSurfaceBinding(conversation, shell.events))
        if self.agent is not None:
            conversation.agent = self.agent
            conversation.bind_agent(self.agent)

    async def detach(self, conversation: Conversation, screen: "MainScreen") -> None:
        self.agent = conversation.agent
        self.shell = conversation._shell
        conversation._shell = None
        if self.shell is not None:
            await self.shell.detach()
        self.directory_watcher = conversation._directory_watcher
        conversation._directory_watcher = None
        if self.directory_watcher is not None:
            self.directory_watcher.rebind(screen)
        if self.agent is not None:
            self.agent.detach_surface(conversation)

    async def close(self) -> None:
        watcher, self.directory_watcher = self.directory_watcher, None
        agent, self.agent = self.agent, None
        shell, self.shell = self.shell, None
        async with AsyncResourceRelease() as release:
            if shell is not None:
                release.push_async_callback(shell.close)
            if agent is not None:
                release.push_async_callback(agent.stop)
            if watcher is not None:
                release.push_async_callback(watcher.aclose)


class MailboxSessionSources(OperationalSessionSources):
    """CLI execution receives user messages through Core's inbox, not ACP."""

    def agent_info(self, conversation: Conversation) -> str:
        scope = conversation.transcript.thread_scope
        return f"@{scope[1]} · CLI inbox" if scope is not None else "CLI inbox"

    def input_ready(self, conversation: Conversation) -> bool:
        return conversation.transcript.readable and conversation.user_message_ready

    def accepts_inbox_submission(self, event) -> bool:
        return not event.shell and bool(event.body.strip())

    def unavailable_reason(self, conversation: Conversation) -> str:
        # A CLI thread has no native owner to start; only its own send or
        # history load can hold the prompt.
        if not conversation.transcript.readable:
            return "Loading thread history…"
        return conversation.send_block_reason or "Send UNKNOWN; inspect, do not retry"


class OperationalSessionPresentation(EditorSessionSurfaceLifetime):
    """Own the editor and logical transcript independently of native membership."""

    def __init__(self) -> None:
        super().__init__()
        from toad.transcript_publication import SessionTranscriptPresentation

        self.transcript = SessionTranscriptPresentation()
        self.sources = OperationalSessionSources()
        self.widget: Conversation | None = None

    @property
    def operational_agent(self):
        return self.widget.agent if self.widget is not None else self.sources.agent

    @property
    def retained_widget_count(self) -> int:
        """The retained native view includes its complete widget tree."""
        return 1 + self.widget.descendant_count if self.widget is not None else 0

    @property
    def retained_source_bytes(self) -> int:
        return self.transcript.retained_source_bytes

    @property
    def retained_paint_bytes(self) -> int:
        # Drawn history rows: about one cell of text and style per column.
        if self.widget is None:
            return 0
        return sum(page.line_count * page.line_width * 8
                   for history in self.widget.window.histories for page in history.pages)

    def compose_content(self, screen: "MainScreen") -> Widget:
        return SessionSurfaceSlot()

    async def prepare(self, screen: "MainScreen") -> None:
        await screen.app.workspace_chrome.native.activate(screen)

    async def retire(self, screen: "MainScreen") -> None:
        await screen.app.workspace_chrome.native.retire(screen)

    async def release_binding(self, conversation: Conversation, screen: "MainScreen") -> None:
        await self.sources.detach(conversation, screen)

    async def attach_binding(self, conversation: Conversation) -> None:
        await self.sources.present(conversation)

    async def apply_coordination(self, screen: "MainScreen", event: CoordinationChangedUpdate) -> None:
        """Apply a coordination update's view work to this session's conversation.

        The workspace admits one session's native tree at a time, so the
        widget may be parked or not yet built. Its work waits for admission,
        which applies the screen's retained fact.
        """
        conversation = self.widget
        if conversation is None:
            return
        if event.worktree is not None and (project := Path(event.worktree)) != conversation.project_path:
            await conversation.sync_project_path(project)
        conversation.input_histories.bind_scope(f"thread:{event.thread.name}")

    @asynccontextmanager
    async def acquire(self, screen: "MainScreen"):
        """Mount owned resources before workspace admission, then restore them.

        The workspace admits the yielded native tree before operational
        attachment can await or publish its restored presentation.
        """
        returning = self.widget is not None
        if not returning:
            slot = screen.query_one(SessionSurfaceSlot)
            content = slot.parent
            assert isinstance(content, Widget)
            self.widget = screen._make_conversation()
            self.widget.display = False
        conversation = self.widget
        self.sources.wire(conversation)
        if not returning:
            if self.state is not None:
                conversation._initial_prompt = self.state.initial_prompt
            await content.mount(conversation, before=slot)
            if (fact := screen.app.coordination_facts.get(screen)) is not None:
                await self.apply_coordination(screen, fact)
        yield conversation
        if self.state is not None:
            self.state.prepare_transcript(conversation)
        await self.transcript.restore_documents()
        if self.state is not None:
            self.state.restore(conversation)
            self.state = None
        await self.attach_binding(conversation)
        await conversation.prepare_retained_session()
        conversation.display = True
        if returning:
            conversation.start_native_session()
        conversation.prompt.focus()

    async def close(self, screen: "MainScreen") -> None:
        self.state = None
        async with AsyncResourceRelease() as release:
            release.push_async_callback(self.sources.close)
            release.push_async_callback(self.transcript.close)
            await screen.app.workspace_chrome.native.dispose(screen)

    async def evict(self) -> None:
        """Release the owned native tree while retaining its actual editor resource."""
        if (conversation := self.widget) is None:
            return
        self.state = SessionViewState.capture(conversation)
        await self.remove_native_tree()

    def capture_reader(self) -> None:
        """The tab is being left: its window keeps the reader's place until it is drawn again."""
        if (conversation := self.widget) is not None:
            conversation.window.park_reader()

    async def remove_native_tree(self) -> None:
        if (conversation := self.widget) is None:
            return
        self.widget = None
        async with AsyncResourceRelease() as release:
            release.push_async_callback(conversation.remove)
            await conversation.release_native_session()


class NativeSessionSurface:
    """Admit session-owned trees without moving their ancestry or copying their state."""

    def __init__(self, app: "ToadApp") -> None:
        self._app = ref(app)
        self.view: MainScreen | None = None
        self._lock = asyncio.Lock()

    @property
    def widget(self) -> Conversation | None:
        return self.view.presentation.widget if self.view is not None else None

    def _presentations(self):
        app = self._app()
        return tuple(presentation for view in app.workspace_sessions.views.values()
                     for presentation in view.retained_native_presentations())

    async def retire(self, screen: "MainScreen") -> None:
        async with self._lock:
            if self.view is not screen or self.widget is None:
                return
            conversation = self.widget
            await conversation.transcript.suspend()
            for history in tuple(conversation.window.histories):
                await history.retire_source(parked=True)
            await screen.presentation.release_binding(conversation, screen)
            conversation.display = False
            self.view = None

    async def activate(self, screen: "MainScreen") -> None:
        async with self._lock:
            if self.view is screen:
                return
            assert self.view is None, "Departing source must retire before admitting the next source"
            async with screen.presentation.acquire(screen) as conversation:
                self.view = screen
            await self._trim_retained(conversation)

    async def reconcile(self, screen: "MainScreen") -> None:
        """Completed rich-panel hydration changes the same native working set."""
        async with self._lock:
            if self.view is screen and self.widget is not None:
                await self._trim_retained(self.widget)

    async def _trim_retained(self, selected: Conversation) -> None:
        """Bound inactive native trees using the existing viewport resource policy.

        The selected presentation is required; its costs participate in the
        same admission as inactive trees. Tab order owns recency and the logical
        session registry owns native membership. Eviction preserves source and
        editor/reader state through the presentation's existing lifetime.
        """
        app = self._app()
        budget = selected.window.presentation_budget
        candidates = {}
        for screen, owner in self._presentations():
            candidates.setdefault(screen.id, []).append(owner)
        required = (self.view.presentation, *(
            owner for owner in candidates.get(self.view.id, ())
            if owner is not self.view.presentation))
        ordered = dict.fromkeys((*required, *(
            owner for identity in app.tab_order.recent
            for owner in candidates.get(identity, ()))))
        admitted = budget.admit(
            ordered, required, app.size.height, app.preparation.max_bytes,
        )
        for owner in ordered:
            if owner not in admitted:
                await owner.evict()

    async def dispose(self, screen: "MainScreen") -> None:
        """Finalize a live tree before pruning; a closed tab retains no editor."""
        async with self._lock:
            owner = screen.presentation
            async with AsyncResourceRelease() as release:
                release.push_async_callback(owner.remove_native_tree)
                if self.view is screen:
                    self.view = None
                    await owner.release_binding(owner.widget, screen)

    async def close(self) -> None:
        async with self._lock:
            if self.view is not None:
                await self.view.presentation.release_binding(self.widget, self.view)
            self.view = None
