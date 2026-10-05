"""Session-owned mounted presentation, with one bounded workspace admission owner."""

import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from weakref import ref

from textual.widget import Widget
from textual.widgets.text_area import TextAreaState

from toad.input_history import InputHistories
from toad.agent_surface import AttachedSurfaceBinding
from toad.widgets.conversation import Conversation
from toad.widgets.history_anchor import ReaderPosition
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
    reader_position: ReaderPosition
    shell_mode: bool
    input_histories: InputHistories
    initial_prompt: str | None

    @classmethod
    def capture(cls, conversation: Conversation) -> "SessionViewState":
        editor = conversation.prompt.prompt_text_area
        return cls(
            editor.capture_editor_state(), conversation.visible_categories,
            ReaderPosition.capture(conversation.window),
            editor.shell_mode, conversation.input_histories, conversation.take_initial_prompt(),
        )

    def restore(self, conversation: Conversation) -> None:
        conversation.input_histories = self.input_histories
        conversation.visible_categories = self.visible_categories
        editor = conversation.prompt.prompt_text_area
        editor.restore_editor_state(self.editor)
        editor.shell_mode = self.shell_mode
        self.reader_position.restore(conversation.window)
        conversation.transcript.reader_position = self.reader_position


class SessionSurfaceLifetime(ABC):
    """A session declares its own UI placement and activation lifetime."""

    @abstractmethod
    def compose_content(self, screen: "MainScreen") -> Widget: ...

    @abstractmethod
    async def prepare(self, screen: "MainScreen") -> None: ...

    @abstractmethod
    async def retire(self, screen: "MainScreen") -> None: ...

    @abstractmethod
    async def close(self, screen: "MainScreen") -> None: ...


class EditorSessionSurfaceLifetime(SessionSurfaceLifetime):
    """Shared actual editor-state custody and active shell close semantics."""

    def __init__(self) -> None:
        self.state: SessionViewState | None = None

    @abstractmethod
    async def release_binding(self, conversation: Conversation, screen: "MainScreen") -> None: ...

    @abstractmethod
    async def attach_binding(self, conversation: Conversation) -> None: ...



class OperationalSessionSources:
    """Logical session custody of existing operational owners, without a view."""

    def __init__(self) -> None:
        self.agent = None
        self.shell = None
        self.directory_watcher = None

    def wire(self, conversation: Conversation) -> None:
        if self.agent is not None:
            from toad.widgets.conversation import ConversationSessionBinding

            conversation.set_reactive(ConversationSessionBinding.agent, self.agent)
        if self.directory_watcher is not None:
            conversation._directory_watcher = self.directory_watcher
            self.directory_watcher.rebind(conversation)

    async def present(self, conversation: Conversation) -> None:
        if self.directory_watcher is not None:
            conversation.call_after_refresh(self.directory_watcher.notify_if_visible)
        if self.shell is not None:
            conversation._shell = self.shell
            await self.shell.attach(AttachedSurfaceBinding(conversation, self.shell.events))
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
        if self.directory_watcher is not None:
            await self.directory_watcher.aclose()
            self.directory_watcher = None
        if self.agent is not None:
            await self.agent.stop()
            self.agent = None
        if self.shell is not None:
            await self.shell.close()
        self.shell = None


class OperationalSessionPresentation(EditorSessionSurfaceLifetime):
    """Own the actual mounted view; eviction retains only its existing editor state."""

    def __init__(self) -> None:
        super().__init__()
        self.sources = OperationalSessionSources()
        self.widget: Conversation | None = None

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
        conversation = self.widget
        self.sources.wire(conversation)
        if not returning:
            if self.state is not None:
                conversation._initial_prompt = self.state.initial_prompt
            await content.mount(conversation, before=slot)
        yield conversation
        await self.attach_binding(conversation)
        if self.state is not None:
            self.state.restore(conversation)
            self.state = None
        await conversation.prepare_retained_session()
        conversation.display = True
        if returning:
            conversation.start_native_session()
        conversation.prompt.focus()

    async def close(self, screen: "MainScreen") -> None:
        await screen.app.workspace_chrome.native.dispose(screen)
        self.state = None
        await self.sources.close()

    async def evict(self) -> None:
        """Release the owned native tree while retaining its actual editor resource."""
        if (conversation := self.widget) is None:
            return
        self.state = SessionViewState.capture(conversation)
        await self.remove_native_tree()

    async def remove_native_tree(self) -> None:
        if (conversation := self.widget) is None:
            return
        await conversation.release_native_session()
        await conversation.remove()
        self.widget = None


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

    async def _trim_retained(self, selected: Conversation) -> None:
        """Bound inactive native trees using the existing viewport resource policy.

        The selected viewport has its ordinary protected/visible admission. Tab
        order owns recency; the logical session registry owns all retained trees.
        There is no second presentation lookup or model store.
        """
        app = self._app()
        budget = selected.window.document_viewport.budget
        candidates = {screen.id: (screen, owner) for screen, owner in self._presentations()
                      if screen is not self.view}
        widgets = source_bytes = 0
        for identity in app.tab_order.recent:
            if identity not in candidates:
                continue
            screen, owner = candidates[identity]
            widget = owner.widget
            viewport = widget.window.document_viewport
            count = 1 + widget.descendant_count
            size = sum(body.retained_source_bytes for key in viewport._warm.values()
                       if (body := key()) is not None)
            if (widgets + count > budget.widget_limit(app.size.height)
                    or source_bytes + size > app.preparation.max_bytes):
                await owner.evict()
            else:
                widgets += count
                source_bytes += size

    async def dispose(self, screen: "MainScreen") -> None:
        """Finalize a live tree before pruning; a closed tab retains no editor."""
        async with self._lock:
            owner = screen.presentation
            if self.view is screen:
                await owner.release_binding(owner.widget, screen)
                self.view = None
            await owner.remove_native_tree()

    async def close(self) -> None:
        async with self._lock:
            if self.view is not None:
                await self.view.presentation.release_binding(self.widget, self.view)
            self.view = None
