"""Per-session editor state and one application-owned blank presentation."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING
from weakref import ref

from textual.screen import Screen
from textual.widget import Widget
from textual.widgets.text_area import Document, EditHistory, Selection, TextAreaState

from toad.history import History
from toad.widgets.conversation import Conversation
from toad.widgets.message_filter import all_categories, MessageCategory

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
    scroll_y: float
    follows_tail: bool
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
            conversation.window.scroll_y, conversation.window.follows_tail,
            editor.shell_mode, conversation.prompt_history, conversation.shell_history,
            conversation.prompt_history_index, conversation.shell_history_index,
        )

    def restore(self, conversation: Conversation) -> None:
        conversation.prompt_history = self.prompt_history
        conversation.shell_history = self.shell_history
        conversation.prompt_history_index = self.prompt_history_index
        conversation.shell_history_index = self.shell_history_index
        conversation.visible_categories = self.visible_categories
        editor = conversation.prompt.prompt_text_area
        editor.restore_editor_state(self.editor)
        editor.shell_mode = self.shell_mode
        if self.follows_tail:
            conversation.window.anchor()
        else:
            conversation.window.release_anchor()
            conversation.window.scroll_to(y=self.scroll_y, animate=False, immediate=True)


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


class OperationalSessionPresentation(SessionSurfaceLifetime):
    """The operational Agent survives; only the selected rich view is mounted."""

    def __init__(self) -> None:
        self.state: SessionViewState | None = None
        self.agent = None
        self._lock = asyncio.Lock()

    def compose_content(self, screen: "MainScreen") -> Widget:
        return SessionSurfaceSlot()

    async def prepare(self, screen: "MainScreen") -> None:
        async with self._lock:
            if screen.query_one_optional(Conversation) is not None:
                return
            conversation = (screen.make_blank_conversation() if self.state is not None
                            else screen._make_conversation())
            await screen.query_one("#session-content").mount(conversation)
            if self.state is not None:
                self.state.restore(conversation)
                self.state = None
            if self.agent is not None:
                conversation.agent = self.agent
                self.agent.presentation.attach_surface(conversation)

    async def retire(self, screen: "MainScreen") -> None:
        async with self._lock:
            conversation = screen.query_one_optional(Conversation)
            if conversation is None:
                return
            self.state = SessionViewState.capture(conversation)
            self.agent = conversation.agent
            if self.agent is not None:
                # Detach before unmount: retiring optional UI must not call stop.
                self.agent.detach_surface(conversation)
            await conversation.remove()

    async def close(self, screen: "MainScreen") -> None:
        # Closing the logical session is distinct from retiring optional UI.
        if self.agent is not None:
            await self.agent.stop()
            self.agent = None
        self.state = None


class BlankSessionPresentation(SessionSurfaceLifetime):
    """One logical blank session, independent of any mounted editor widget."""

    def __init__(self) -> None:
        self.state: SessionViewState | None = None

    @property
    def editor_state(self) -> TextAreaState | None:
        return self.state.editor if self.state is not None else None

    def compose_content(self, screen: "MainScreen") -> Widget:
        return SessionSurfaceSlot()

    async def prepare(self, screen: "MainScreen") -> None:
        # Actual shell/agent use promotes the editor to a retained presentation.
        if screen.query_one_optional(Conversation) is None:
            await screen.app.workspace_chrome.blank.activate(screen, self)

    async def retire(self, screen: "MainScreen") -> None:
        # WorkspaceChrome has moved or parked the surface, capturing this
        # session's editor before changing custody. No duplicate state owner.
        return

    async def close(self, screen: "MainScreen") -> None:
        self.state = None


class BlankSessionSurface:
    """One native blank editor tree; session controllers own document identity."""

    def __init__(self, app: "ToadApp") -> None:
        self._app = ref(app)
        self.widget: Conversation | None = None
        self.owner: BlankSessionPresentation | None = None
        self._lock = asyncio.Lock()

    @property
    def app(self) -> "ToadApp":
        app = self._app()
        if app is None:
            raise ReferenceError("The blank workspace owner has retired")
        return app

    @staticmethod
    def _can_transfer(screen: "MainScreen", conversation: Conversation) -> bool:
        return (
            screen._agent is None and conversation.agent is None
            and conversation._agent_data is None and conversation._shell is None
            and not conversation.contents.children and not conversation.terminals
            and conversation._terminal is None and conversation.goal is None
            and not conversation.queued_prompts and not conversation.queue_projection.items
            and not conversation.unresolved_inputs
            and not conversation.status and conversation.native_history_status is None
            and not conversation.input_delivery_error
            and conversation.prompt._ask is None and not conversation.prompt.ask_queue
            and conversation._initial_prompt is None and not conversation.prompt.disabled
            and not conversation.prompt.prompt_text_area.disabled
        )

    async def _release_owner(self) -> None:
        widget, owner = self.widget, self.owner
        if widget is None or owner is None:
            return
        from toad.screens.main import MainScreen

        screen = widget.screen
        assert isinstance(screen, MainScreen)
        if not self._can_transfer(screen, widget):
            # First operational use changes custody in place. Detach its source
            # before admitting another rich blank surface; keep no old UI tree.
            screen.presentation = OperationalSessionPresentation()
            self.widget = None
            self.owner = None
            await screen.presentation.retire(screen)
            return
        owner.state = SessionViewState.capture(widget)
        self.owner = None

    def _move(self, parent: Widget, slot: Widget | None = None) -> None:
        widget = self.widget
        assert widget is not None
        if widget.parent is parent:
            return
        captured = self.app.mouse_captured
        if captured is not None and widget in captured.ancestors_with_self:
            captured.release_mouse()
        previous = widget.screen
        widget.reparent(parent, before=slot)
        widget.window.rebind_screen(previous, widget.screen)

    async def activate(self, screen: "MainScreen", owner: BlankSessionPresentation) -> None:
        async with self._lock:
            if self.owner is owner and self.widget is not None and self.widget.screen is screen:
                return
            await self._release_owner()
            slot = screen.query_one(SessionSurfaceSlot)
            content = slot.parent
            assert isinstance(content, Widget)
            if self.widget is None:
                self.widget = screen.make_blank_conversation()
                await content.mount(self.widget, before=slot)
            else:
                self._move(content, slot)
                self.widget.display = True
            conversation = self.widget
            if conversation.project_path != screen.project_path:
                # A retained editor may cross project roots. Its watcher and
                # history scope follow the actual session through the existing
                # project-path owner, not just a cosmetic reactive assignment.
                await conversation.sync_project_path(screen.project_path)
            if (state := owner.state) is None:
                # load_text clears its current EditHistory in place. That history
                # belongs to the departing session; install independent model
                # objects before presenting a new logical session.
                editor = conversation.prompt.prompt_text_area
                previous = editor.history
                editor.restore_editor_state(TextAreaState(
                    Document(""), EditHistory(previous.max_checkpoints,
                                              previous.checkpoint_timer,
                                              previous.checkpoint_max_characters),
                    Selection.cursor((0, 0)), 0, 0, None, (), None,
                ))
                editor.shell_mode = False
                conversation.visible_categories = all_categories()
                conversation.prompt_history = History(conversation._prompt_history_path())
                conversation.shell_history = History(conversation.project_data_path / "shell_history.jsonl")
                conversation.prompt_history_index = conversation.shell_history_index = 0
                conversation.window.anchor()
            else:
                state.restore(conversation)
                owner.state = None
            conversation.column = screen.column
            self.owner = owner

    async def park_away_from(self, screen: Screen) -> None:
        async with self._lock:
            widget = self.widget
            if widget is None or widget.screen is screen:
                return
            await self._release_owner()
            if self.widget is None:
                return
            # Only the selected editor is admitted. The actual document and
            # undo objects already belong to the departing session's state.
            await self.widget.remove()
            self.widget = None
