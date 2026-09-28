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
from toad.screens.session_view import SessionView
from toad.widgets.conversation import Conversation
from toad.widgets.message_filter import MessageCategory, all_categories

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.screens.main import MainScreen


class BlankSurfaceSlot(Widget):
    """A blank session declares placement but owns no second editor tree."""

    DEFAULT_CSS = "BlankSurfaceSlot { display: none; }"


class BlankParkingScreen(SessionView):
    """Inactive app-owned custody for the single blank editor between view kinds."""

    DEFAULT_CSS = "BlankParkingScreen { display: none; }"


@dataclass(frozen=True)
class BlankViewState:
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


class SessionSurfaceLifetime(ABC):
    """A session declares its own UI placement and activation lifetime."""

    @abstractmethod
    def compose_content(self, screen: "MainScreen") -> Widget: ...

    @abstractmethod
    def defer_thread_panels(self, screen: "MainScreen") -> bool: ...

    @abstractmethod
    def hydrate_thread_panels_on_reveal(self) -> bool: ...

    @abstractmethod
    async def prepare(self, screen: "MainScreen") -> None: ...

    @abstractmethod
    async def retire(self, screen: "MainScreen") -> None: ...


class RetainedSessionPresentation(SessionSurfaceLifetime):
    """Executing agents keep their actual message target and rich view attached."""

    def compose_content(self, screen: "MainScreen") -> Widget:
        return screen._make_conversation()

    def defer_thread_panels(self, screen: "MainScreen") -> bool:
        return not screen._content_loaded

    def hydrate_thread_panels_on_reveal(self) -> bool:
        return False

    async def prepare(self, screen: "MainScreen") -> None:
        return

    async def retire(self, screen: "MainScreen") -> None:
        return


class BlankSessionPresentation(SessionSurfaceLifetime):
    """One logical blank session, independent of any mounted editor widget."""

    def __init__(self) -> None:
        self.state: BlankViewState | None = None

    @property
    def editor_state(self) -> TextAreaState | None:
        return self.state.editor if self.state is not None else None

    def compose_content(self, screen: "MainScreen") -> Widget:
        return BlankSurfaceSlot()

    def defer_thread_panels(self, screen: "MainScreen") -> bool:
        return True

    def hydrate_thread_panels_on_reveal(self) -> bool:
        return True

    async def prepare(self, screen: "MainScreen") -> None:
        # Actual shell/agent use promotes the editor to a retained presentation.
        if screen.query_one_optional(Conversation) is None:
            await screen.app.workspace_chrome.blank.activate(screen, self)

    async def retire(self, screen: "MainScreen") -> None:
        # WorkspaceChrome has moved or parked the surface, capturing this
        # session's editor before changing custody. No duplicate state owner.
        return


class BlankSessionSurface:
    """One native blank editor tree; session controllers own document identity."""

    PARKING_MODE = "_blank_workspace_parking"

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
            and conversation._terminal is None and not conversation.goal_display.visible
            and not conversation.queued_prompts and not conversation.queue_projection.items
            and not conversation.unresolved_inputs
            and not conversation.status and conversation.native_history_status is None
            and not conversation.input_delivery_error
            and conversation.prompt._ask is None and not conversation.prompt.ask_queue
            and conversation._initial_prompt is None and not conversation.prompt.disabled
            and not conversation.prompt.prompt_text_area.disabled
        )

    @staticmethod
    def _capture(conversation: Conversation) -> BlankViewState:
        editor = conversation.prompt.prompt_text_area
        return BlankViewState(
            editor.capture_editor_state(), conversation.visible_categories,
            conversation.window.scroll_y, conversation.window.follows_tail,
            editor.shell_mode, conversation.prompt_history, conversation.shell_history,
            conversation.prompt_history_index, conversation.shell_history_index,
        )

    def _release_owner(self) -> None:
        widget, owner = self.widget, self.owner
        if widget is None or owner is None:
            return
        from toad.screens.main import MainScreen

        screen = widget.screen
        assert isinstance(screen, MainScreen)
        if not self._can_transfer(screen, widget):
            # A real shell, agent, transcript or unresolved input now owns this
            # view. Keep it attached to that session and start a new blank tree.
            self.widget = None
            self.owner = None
            return
        owner.state = self._capture(widget)
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
            self._release_owner()
            slot = screen.query_one(BlankSurfaceSlot)
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
                conversation.prompt_history = state.prompt_history
                conversation.shell_history = state.shell_history
                conversation.prompt_history_index = state.prompt_history_index
                conversation.shell_history_index = state.shell_history_index
                conversation.visible_categories = state.visible_categories
                conversation.prompt.prompt_text_area.restore_editor_state(state.editor)
                conversation.prompt.prompt_text_area.shell_mode = state.shell_mode
                if state.follows_tail:
                    conversation.window.anchor()
                else:
                    conversation.window.release_anchor()
                    conversation.window.scroll_to(y=state.scroll_y, animate=False, immediate=True)
                owner.state = None
            conversation.column = screen.column
            self.owner = owner

    async def park_away_from(self, screen: Screen) -> None:
        async with self._lock:
            widget = self.widget
            if widget is None or widget.screen is screen:
                return
            self._release_owner()
            if self.widget is None:
                return
            app = self.app
            if self.PARKING_MODE not in app._modes:
                app.add_mode(self.PARKING_MODE, BlankParkingScreen)
            await app._init_mode(self.PARKING_MODE)
            parking = app.get_screen_stack(self.PARKING_MODE)[0]
            self._move(parking)
            self.widget.display = False
