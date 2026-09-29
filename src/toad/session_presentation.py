"""Per-session editor state and one application-owned blank presentation."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING
from weakref import ref

from textual.widget import Widget
from textual.widgets.text_area import Document, EditHistory, Selection, TextAreaState

from toad.history import History
from toad.widgets.conversation import Conversation
from toad.widgets.history_anchor import ReaderPosition
from toad.widgets.message_filter import MessageCategory

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.screens.main import MainScreen


class SessionSurfaceSlot(Widget):
    """A blank session declares placement but owns no second editor tree."""

    DEFAULT_CSS = "SessionSurfaceSlot { display: none; }"


@dataclass(frozen=True)
class SessionViewState:
    """The actual editor document/history and reader intent, not a transcript copy."""

    editor: TextAreaState
    visible_categories: frozenset[type[MessageCategory]]
    reader_position: ReaderPosition
    shell_mode: bool
    prompt_history: History
    shell_history: History
    prompt_history_index: int
    shell_history_index: int

    @classmethod
    def capture(cls, conversation: Conversation) -> "SessionViewState":
        editor = conversation.prompt.prompt_text_area
        return cls(
            editor.capture_editor_state(), conversation.visible_categories,
            ReaderPosition.capture(conversation.window),
            editor.shell_mode, conversation.prompt_history, conversation.shell_history,
            conversation.prompt_history_index, conversation.shell_history_index,
        )

    def restore(self, conversation: Conversation) -> None:
        conversation.prompt_history = self.prompt_history
        conversation.shell_history = self.shell_history
        # Restore reader intent without executing history navigation again.
        # Its watchers load text and would replace the retained editor document.
        conversation.set_reactive(Conversation.prompt_history_index, self.prompt_history_index)
        conversation.set_reactive(Conversation.shell_history_index, self.shell_history_index)
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
            self.agent.attach_surface(conversation)

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

    async def close(self, screen: "MainScreen") -> None:
        if self.directory_watcher is not None:
            await self.directory_watcher.aclose()
            self.directory_watcher = None
        if self.agent is not None:
            await self.agent.stop()
            self.agent = None
        conversation = screen.query_one_optional(Conversation)
        shell = conversation._shell if conversation is not None else self.shell
        if shell is not None:
            await shell.close()
        self.shell = None


class OperationalSessionPresentation(EditorSessionSurfaceLifetime):
    """The operational Agent survives; only the selected rich view is mounted."""

    def __init__(self) -> None:
        super().__init__()
        self.sources = OperationalSessionSources()

    def compose_content(self, screen: "MainScreen") -> Widget:
        return SessionSurfaceSlot()

    async def prepare(self, screen: "MainScreen") -> None:
        await screen.app.workspace_chrome.native.activate(screen, self)

    async def retire(self, screen: "MainScreen") -> None:
        await screen.app.workspace_chrome.native.retire(screen, self)

    async def release_binding(self, conversation: Conversation, screen: "MainScreen") -> None:
        self.state = SessionViewState.capture(conversation)
        await self.sources.detach(conversation, screen)

    async def attach_binding(self, conversation: Conversation) -> None:
        self.sources.wire(conversation)
        await self.sources.present(conversation)

    async def close(self, screen: "MainScreen") -> None:
        await self.sources.close(screen)
        self.state = None


class NativeSessionSurface:
    """One bounded rich native surface; each logical owner retains its real state."""

    def __init__(self, app: "ToadApp") -> None:
        self._app = ref(app)
        self.widget: Conversation | None = None
        self.owner: EditorSessionSurfaceLifetime | None = None
        self.view: MainScreen | None = None
        self._lock = asyncio.Lock()

    async def retire(self, screen: "MainScreen", owner: EditorSessionSurfaceLifetime) -> None:
        async with self._lock:
            if self.owner is not owner or self.widget is None:
                return
            await owner.release_binding(self.widget, screen)
            await self.widget.window.document_viewport.park_source()
            await self.widget.release_native_session()
            self.widget.display = False
            self.owner = None
            self.view = None

    async def activate(self, screen: "MainScreen", owner: EditorSessionSurfaceLifetime) -> None:
        async with self._lock:
            if self.owner is owner and self.view is screen:
                return
            slot = screen.query_one(SessionSurfaceSlot)
            content = slot.parent
            assert isinstance(content, Widget)
            first = self.widget is None
            if first:
                self.widget = screen._make_conversation()
                await content.mount(self.widget, before=slot)
            else:
                assert self.owner is None, "Departing source must retire before admitting the next source"
                self.widget.reparent(content, before=slot)
                await self.widget.bind_native_session(screen)
            conversation = self.widget
            await owner.attach_binding(conversation)
            if owner.state is not None:
                owner.state.restore(conversation)
                owner.state = None
            elif not first:
                editor = conversation.prompt.prompt_text_area
                previous = editor.history
                editor.restore_editor_state(TextAreaState(
                    Document(""), EditHistory(previous.max_checkpoints,
                                              previous.checkpoint_timer,
                                              previous.checkpoint_max_characters),
                    Selection.cursor((0, 0)), 0, 0, None, (), None))
            self.owner, self.view = owner, screen
            conversation.display = True
            conversation.window.document_viewport.resume_source()
            if not first:
                conversation.start_native_session()
            conversation.prompt.focus()

    async def close(self) -> None:
        async with self._lock:
            if self.widget is not None:
                if self.owner is not None and self.view is not None:
                    await self.owner.release_binding(self.widget, self.view)
                await self.widget.release_native_session()
                await self.widget.remove()
            self.widget = self.owner = self.view = None
