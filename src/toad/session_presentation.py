"""Session-owned mounted presentation, with one bounded workspace admission owner."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING
from weakref import ref

from textual.widget import Widget
from textual.widgets.text_area import TextAreaState

from toad.input_history import InputHistories
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
            editor.shell_mode, conversation.input_histories, conversation._initial_prompt,
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
        if self.directory_watcher is not None:
            conversation._directory_watcher = self.directory_watcher
            self.directory_watcher.rebind(conversation)

    async def present(self, conversation: Conversation) -> None:
        if self.directory_watcher is not None:
            conversation.call_after_refresh(self.directory_watcher.notify_if_visible)
        if self.shell is not None:
            conversation._shell = self.shell
            await self.shell.attach(conversation)
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
        await screen.app.workspace_chrome.native.activate(screen, self)

    async def retire(self, screen: "MainScreen") -> None:
        await screen.app.workspace_chrome.native.retire(screen, self)

    async def release_binding(self, conversation: Conversation, screen: "MainScreen") -> None:
        await self.sources.detach(conversation, screen)

    async def attach_binding(self, conversation: Conversation) -> None:
        self.sources.wire(conversation)
        await self.sources.present(conversation)

    async def close(self, screen: "MainScreen") -> None:
        await screen.app.workspace_chrome.native.dispose(screen, self)
        await self.sources.close()
        self.state = None


class NativeSessionSurface:
    """Admit session-owned trees without moving their ancestry or copying their state."""

    def __init__(self, app: "ToadApp") -> None:
        self._app = ref(app)
        self.owner: OperationalSessionPresentation | None = None
        self.view: MainScreen | None = None
        self._lock = asyncio.Lock()

    @property
    def widget(self) -> Conversation | None:
        return self.owner.widget if self.owner is not None else None

    def _presentations(self):
        app = self._app()
        return tuple(presentation for view in app.workspace_sessions.views.values()
                     for presentation in view.retained_native_presentations())

    async def retire(self, screen: "MainScreen", owner: OperationalSessionPresentation) -> None:
        async with self._lock:
            if self.owner is not owner or self.widget is None:
                return
            conversation = self.widget
            await conversation.window.document_viewport.suspend_source()
            await conversation.transcript.suspend()
            for history in tuple(conversation.window.histories):
                await history.retire_source(parked=True)
            await owner.release_binding(conversation, screen)
            conversation.display = False
            self.owner = None
            self.view = None

    async def activate(self, screen: "MainScreen", owner: OperationalSessionPresentation) -> None:
        async with self._lock:
            if self.owner is owner and self.view is screen:
                return
            assert self.owner is None, "Departing source must retire before admitting the next source"
            returning = owner.widget is not None
            if not returning:
                slot = screen.query_one(SessionSurfaceSlot)
                content = slot.parent
                assert isinstance(content, Widget)
                owner.widget = screen._make_conversation()
                if owner.sources.agent is not None:
                    from toad.widgets.conversation import ConversationSessionBinding

                    owner.widget.set_reactive(ConversationSessionBinding.agent, owner.sources.agent)
                if owner.state is not None:
                    owner.widget._initial_prompt = owner.state.initial_prompt
                await content.mount(owner.widget, before=slot)
            conversation = owner.widget
            self.owner, self.view = owner, screen
            await owner.attach_binding(conversation)
            if owner.state is not None:
                owner.state.restore(conversation)
                owner.state = None
            await conversation.prepare_retained_session()
            conversation.display = True
            conversation.window.document_viewport.resume_source()
            if returning:
                conversation.start_native_session()
            conversation.prompt.focus()
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
                      if owner is not self.owner}
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
                await self._evict(screen, owner)
            else:
                widgets += count
                source_bytes += size

    async def _evict(self, screen: "MainScreen", owner: OperationalSessionPresentation) -> None:
        if (conversation := owner.widget) is None:
            return
        owner.state = SessionViewState.capture(conversation)
        await self._remove(owner)

    async def _remove(self, owner: OperationalSessionPresentation) -> None:
        if (conversation := owner.widget) is None:
            return
        await conversation.release_native_session()
        await conversation.window.document_viewport.close()
        await conversation.remove()
        owner.widget = None

    async def dispose(self, screen: "MainScreen", owner: OperationalSessionPresentation) -> None:
        """Finalize a live tree before pruning; a closed tab retains no editor."""
        async with self._lock:
            if self.owner is owner:
                await owner.release_binding(owner.widget, screen)
                self.owner = self.view = None
            await self._remove(owner)
            owner.state = None

    async def close(self) -> None:
        async with self._lock:
            if self.owner is not None:
                await self.owner.release_binding(self.widget, self.view)
            self.owner = self.view = None
            for screen, owner in self._presentations():
                await self._remove(owner)
                owner.state = None
