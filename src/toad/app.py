from toad.core import events as core_events
from toad.core_event_carrier import CoreEventMessage
from toad.workspace_sessions import WorkspaceSessionShutdown
from inspect import isabstract
from toad.comms_root import CoordinationAccess

from toad.thread_actions import ThreadActions
from toad.widgets.comms_transfer import Transfers
import asyncio
import signal
import traceback
import gc
import sys
import json
import os
from enum import IntEnum
from functools import cached_property, partial
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Callable, Never, TypeVar, cast

from agent_comms.acp_extension import TranscriptChangedUpdate
from rich.console import RenderableType
from textual._time import after_input
from textual import events, on, work
from textual.app import App
from textual.await_complete import AwaitComplete
from textual.content import Content
from textual.css.scalar import Scalar, Unit
from textual.notifications import Notify
from textual.reactive import var
from textual.screen import Screen

from toad import messages
from toad.core import session_requests
from toad.core_event_carrier import CoreEventReceiver
from agent_comms.mro_dispatch import handles
from toad.session_scope import AgentBinding
from toad.render_backend import Renderer
from toad.work_preparation import PreparationRuntime
from toad.navigation_preparation import (
    NavigationReader,
)
from toad.db import DB
from toad.preferences import SavedSettings
from toad.session_tracker import (
    OpenTab,
    SessionDetails,
    SessionTracker,
    SidebarState,
)
from toad.sidebar_layout import SidebarLayout
from toad.clipboard import Clipboard
from toad.constants import WELCOME
from toad.tab_order import TabOrder
from toad.thread_navigation import ThreadNavigator
from toad.session_navigation import SessionNavigation
from toad.terminal_attention import TerminalAttention
from toad.textual_colours import ThemedApp
from toad.application_actions import ApplicationCommands
from toad.widget_actions import ApplicationAction, DeclaredWidgetActions
from toad.application_lifetime import ApplicationLifetime, Ended, Succeeded, TerminalOutcome
from toad.resource_release import AsyncResourceRelease

if TYPE_CHECKING:
    from agent_comms.launch_runtime import LaunchRuntime
    from toad.db import DB
    from toad.render_backend import RenderTask
    from toad.screens.main import MainScreen
    from toad.screens.store import StoreScreen

RenderResultT = TypeVar("RenderResultT")




def get_workspace_screen():
    from toad.screens.workspace import WorkspaceScreen
    return WorkspaceScreen(id="workspace")


def get_store_screen() -> StoreScreen:
    """Get the store screen (lazily loaded)."""
    from toad.screens.store import StoreScreen

    return StoreScreen()


class HeapBeforeFreeze:
    """The heap is not frozen yet; the first painted history freezes it.

    The one freeze point: by then the modules, classes, type caches, the
    workspace and the first tab's history exist and mostly live as long as the
    process, so the cyclic collector stops scanning them (Python 3.14 scans the
    whole live heap periodically: ~70,000 objects took 12-18 ms, inside
    whatever callback was running). Anything alive then that later dies in a
    reference cycle is never collected; that is at most the heap at that
    moment (decision 2026-10-11, about 6-10 MB).
    """

    def history_displayed(self, app: ToadApp) -> None:
        gc.freeze()
        app.heap = HeapFrozen()


class HeapFrozen:
    """The one freeze has happened."""

    def history_displayed(self, app: ToadApp) -> None:
        pass


class ApplicationNotRunningError(RuntimeError):
    """The application has no event loop to accept cross-thread work."""


class ScreenWidth(IntEnum):
    """Native sizing modes; legacy breakpoint classes are derived from them."""

    side_panel_width: Scalar | None

    def __new__(cls, minimum_width: int, side_panel_width: Scalar | None):
        mode = int.__new__(cls, minimum_width)
        mode._value_ = minimum_width
        mode.side_panel_width = side_panel_width
        return mode

    NARROW = (0, None)
    WIDE = (100, Scalar(50, Unit.PERCENT, Unit.WIDTH))


class ToadApp(CoreEventReceiver, DeclaredWidgetActions, WorkspaceSessionShutdown, ThemedApp, App[TerminalOutcome], inherit_bindings=False):
    """The top level app."""

    CSS_PATH = ["toad.tcss", "screens/comms.tcss"]
    COMMANDS = {ApplicationCommands}
    MODES = {"store": get_store_screen, "workspace": get_workspace_screen}
    BINDING_GROUP_TITLE = "System"
    ACTIONS = ApplicationAction
    ALLOW_IN_MAXIMIZED_VIEW = ""

    project_dir = var(Path)
    show_sessions = var(False)

    HORIZONTAL_BREAKPOINTS: list[tuple[int, str]] = [
        (mode, f"-{mode.name.lower()}") for mode in ScreenWidth
    ]

    PAUSE_GC_ON_SCROLL = True

    def __init__(
        self,
        agent_binding: AgentBinding,
        project_dir: str | None = None,
        mode: str | None = None,
        agent_session_id: str | None = None,
    ) -> None:
        """Toad app.

        Args:
            agent_binding: The agent selected at startup.
            project_dir: Project directory.
            mode: Initial mode.
        """
        from toad.render_processes import RenderProcessPool
        from toad.render_backend import PreparedRenderer

        Renderer.prepare_spawn()
        self.events = core_events.CoreEventStream(self)
        self.preparation = PreparationRuntime(RenderProcessPool())
        self.render_processes: Renderer = PreparedRenderer(self.preparation)
        self.background_render_slots = asyncio.Semaphore(1)
        self._background_render_tasks: set[asyncio.Task[object]] = set()
        self.navigation_reader = NavigationReader()
        self.agent_binding = agent_binding

        self.application = ApplicationLifetime(self, agent_session_id)
        self.clipboard_transport = Clipboard.for_platform()
        self.terminal_attention = TerminalAttention(self)

        self.session_navigation = SessionNavigation(self)
        self.thread_navigation = ThreadNavigator(self)
        self.thread_actions = ThreadActions(self)
        self.transfers = Transfers(self)
        self.sidebar_state = SidebarState()
        self.sidebar_layout = SidebarLayout()
        self._mode_switch_lock = asyncio.Lock()
        self.tab_order = TabOrder(
            lambda identity, index: self.select_session(identity.mode_name, history_index=index),
            home=mode or WELCOME,
            db=DB(),
        )
        self._session_tracker = SessionTracker(self.tab_order)
        self.coordination_access = CoordinationAccess(self)

        from toad.file_kind import FileKind
        FileKind.prepare_terminal()
        super().__init__()
        self._return_value: TerminalOutcome = Ended(self.application.version)
        self.session_navigation.bind_events()
        self.project_dir = Path(project_dir or "./").expanduser().resolve()

    @property
    def return_value(self) -> TerminalOutcome:
        return self._return_value

    def exit(
        self, result: TerminalOutcome | None = None, return_code: int = 0,
        message: RenderableType | None = None,
    ) -> None:
        """Textual's omitted result is a normal terminal ending."""
        super().exit(
            Ended(self.application.version) if result is None else result,
            return_code=return_code, message=message,
        )

    def succeed_onto(self, runtime: LaunchRuntime) -> Never:
        self.call_from_thread(self.exit, Succeeded(runtime))
        raise asyncio.CancelledError


    async def _close_all(self) -> None:
        # View release can fail. The application still owns its observation
        # pipe and process pools; an Unmount event may never follow that error.
        async with AsyncResourceRelease() as release:
            release.callback(self.terminal_attention.close)
            release.callback(self.colours.stop)
            release.push_async_callback(self.coordination_access.close)
            # Accepted preparation survives its UI waiter. Keep the observer
            # available until those workers and their read replies finish.
            release.push_async_callback(self.render_processes.aclose)
            release.push_async_callback(self.navigation_reader.aclose)
            release.push_async_callback(super()._close_all)
            release.push_async_callback(self.coordination_access.stop_observing)
            release.push_async_callback(self.thread_actions.close)
            release.push_async_callback(self.thread_navigation.close)
        if self._background_render_tasks:
            await asyncio.gather(*tuple(self._background_render_tasks), return_exceptions=True)

    async def prepare_background(self, task: RenderTask[RenderResultT]) -> RenderResultT:
        """Keep the background work slot occupied until the renderer really finishes."""
        await self.background_render_slots.acquire()
        try:
            pending = asyncio.create_task(self.render_processes.submit(task), name="background-render-preparation")
        except BaseException:
            self.background_render_slots.release()
            raise
        tracked = cast(asyncio.Task[object], pending)
        self._background_render_tasks.add(tracked)
        tracked.add_done_callback(self._background_render_finished)
        await asyncio.wait((pending,))
        return pending.result()

    def _background_render_finished(self, task: asyncio.Task[object]) -> None:
        self._background_render_tasks.discard(task)
        if not task.cancelled():
            task.exception()
        self.background_render_slots.release()


    def open_settings(self) -> SavedSettings:
        return SavedSettings.open(self)

    async def get_db(self) -> DB:
        """Get an instance of the database."""
        db = DB()
        return db


    @property
    def session_tracker(self) -> SessionTracker:
        return self._session_tracker

    def publish_clipboard(self, text: str) -> None:
        self.clipboard_transport = self.clipboard_transport.publish(self, text)


    def on_notify(self, event: Notify) -> None:
        self.terminal_attention.notification(event.notification)

    def _handle_exception(self, error: Exception) -> bool:
        """The mounted application owns escaped handler and worker errors."""
        if not self.screen_stack or not self.screen.is_mounted:
            return super()._handle_exception(error)
        self.show_error("".join(traceback.format_exception(error)), type(error).__name__)
        return True

    async def on_load(self) -> None:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, self.exit)
        self.preparation.renderer.start()
        self._prewarm_conversation_css()
        db = await self.get_db()
        await db.create()
        self.saved_settings.ensure_file(self)
        self.colours.start()
        self.saved_settings.apply_all()

    def _prewarm_conversation_css(self) -> None:
        """Load known conversation classes' default CSS in one parse.

        The classes are discovered through their ordinary inheritance rather
        than maintaining a manual list of every channel, tool and Markdown
        component. Registration deduplicates identical sources when widgets
        eventually mount, avoiding a full CSS rebuild of already-open tabs.
        """
        from textual.widget import Widget
        from textual.widgets._footer import KeyGroup
        from textual.widgets.markdown import Markdown

        from toad.screens import comms, main  # noqa: F401 - register widget classes
        from toad.widgets import tool_call  # noqa: F401 - register widget classes

        started = monotonic()
        source_count = len(self.stylesheet.source)
        pending = [Widget]
        seen: set[type[Widget]] = set()
        markdown_blocks = set(Markdown.BLOCKS.values())
        while pending:
            owner = pending.pop()
            for widget_type in owner.__subclasses__():
                if widget_type in seen:
                    continue
                seen.add(widget_type)
                pending.append(widget_type)
                if not (widget_type.__module__.startswith("toad.")
                        or widget_type in markdown_blocks or widget_type is KeyGroup) or isabstract(widget_type):
                    continue
                for read_from, css, tie_breaker, scope in widget_type._get_default_css(
                    object.__new__(widget_type)
                ):
                    self.stylesheet.add_source(css, read_from=read_from,
                                               is_default_css=True, tie_breaker=tie_breaker,
                                               scope=scope)
        self.stylesheet.parse()
        if root := os.environ.get("TOAD_PERF_INSTANCE"):
            (Path(root) / "css-prewarm.json").write_text(json.dumps({
                "sources_added": len(self.stylesheet.source) - source_count,
                "duration_ms": (monotonic() - started) * 1000,
            }))


    def select_session(self, mode: str, *, history_index: int | None = None) -> AwaitComplete:
        if mode != self.selected_mode:
            self.navigation_reader.invalidate()
        self.session_navigation.entered(mode, self.selected_mode)
        return AwaitComplete(self._switch_mode_ready(mode, history_index=history_index))

    async def _switch_mode_ready(self, mode: str, *, history_index: int | None = None) -> None:
        async with self._mode_switch_lock:
            previous = self.selected_mode
            try:
                # Source retirement and native preparation may await I/O,
                # child pumps or compensated layout. Their original owners
                # fence those mutations; holding a global paint batch here
                # also withholds the frames those operations may need.
                if mode == "store":
                    await self.workspace_sessions.retire()
                    await super().switch_mode("store")
                else:
                    if self.current_mode != "workspace":
                        await super().switch_mode("workspace")
                    # A switch is several frames of work: hold the workspace's
                    # frames and let the loop run due input and timers between steps, so input is
                    # never held behind the whole switch and no half-switched
                    # scene is written. Layout still runs for steps that measure.
                    with self.workspace_screen.hold_frames():
                        await self.workspace_sessions.select(mode)
                        await after_input()
                        await self.workspace_screen.prepare_navigation()
                        await after_input()
                        await self.workspace_screen.layout_navigation()
                if mode != previous:
                    if entry := self.session_navigation.get(mode):
                        self.tab_order.record_visit(entry.identity, history_index)
                    self.events.publish(core_events.SessionSelected(mode, previous))
            finally:
                self.screen.refresh()


    @property
    def open_tabs(self) -> tuple[OpenTab, ...]:
        return self.session_navigation.tabs

    @cached_property
    def workspace_chrome(self):
        from toad.workspace_chrome import WorkspaceChrome

        return WorkspaceChrome(self)

    @cached_property
    def workspace_sessions(self):
        from toad.workspace_sessions import WorkspaceSessions
        return WorkspaceSessions(self)

    @property
    def workspace_screen(self):
        return self.get_screen_stack("workspace")[0]

    @property
    def selected_session(self):
        return self.workspace_sessions.source.view

    @property
    def selected_mode(self):
        return (self.workspace_sessions.source.identity
                if self.current_mode == "workspace" else self.current_mode)


    def local_coordination_threads(self) -> set[str]:
        """Authoritative wire identities already represented by local sessions."""
        threads: set[str] = set()
        for details in self.session_tracker.ordered_sessions:
            screen = self.session_navigation.source(details.mode_name)
            if screen is not None and screen.coordination_root is not None:
                threads.add(screen.thread_identity.thread_name())
        return threads

    async def registry_names(self) -> list[str]:
        """Read peers through the current coordination owner, independent of panels."""
        registered = await self.preparation.run_thread(
            lambda: tuple(self.coordination_access.observation.observed().service.registry.active_threads()))
        local_threads = self.local_coordination_threads()
        return [name for name in registered if name not in local_threads]

    @property
    def running_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None:
            raise ApplicationNotRunningError("App is not running")
        return loop

    def schedule_from_thread(self, callback: Callable[[], object]) -> None:
        """Schedule work with this App's context from outside its event loop."""
        loop = self.running_loop

        def run() -> None:
            with self._context():
                callback()

        loop.call_soon_threadsafe(run)

    async def on_mount(self) -> None:
        # The terminal driver is running now, so ANSI themes can query its colours.
        await self.colours.mount()
        self.coordination_access.start()
        await self.application.start()
        # Background threads (Core reads, preparation) give the GIL back to
        # the UI thread within 1 ms instead of the default 5 ms.
        sys.setswitchinterval(0.001)

    heap: HeapBeforeFreeze | HeapFrozen = HeapBeforeFreeze()
    """Whether the heap's one freeze has happened (see HeapBeforeFreeze)."""

    def history_displayed(self) -> None:
        """A view's history was painted."""
        self.heap.history_displayed(self)
        self.selected_session.mark_visible()

    @handles(session_requests.WorkspaceSessionRequest)
    async def on_workspace_session_request(self, event: CoreEventMessage) -> None:
        await event.event.apply(self.session_navigation)

    @on(events.TextSelected)
    async def on_text_selected(self) -> None:
        if self.settings.ui.auto_copy:
            if selection := self.screen.get_selected_text():
                self.copy_to_clipboard(selection)
                self.notify(
                    "Copied selection to clipboard (see settings)",
                    title="Automatic copy",
                )

    async def dispatch_style_action(self, handler, event, default_namespace) -> bool:
        """Right-click adds its menu to the original decoded link action."""
        if isinstance(event, events.Click) and event.button == 3:
            from toad.line_blocks import LineLink
            link = None
            match handler.action:
                case ("", "open", (LineLink() as target,)):
                    link = target
                case ("", "link", (str() as href,)) if href.startswith("toad-link:"):
                    link = LineLink.from_href(href)
            if link is not None and await link.copy_menu(default_namespace, event):
                return True
        return await super().dispatch_style_action(handler, event, default_namespace)

    def _set_mouse_over(self, widget, hover_widget) -> None:
        # Textual normally clears and reapplies the *same* :hover styles on
        # every pointer move, including every step of a text-selection drag.
        # The widget's own layout/class invalidation already refreshes styles;
        # neither hover ownership nor pseudo-classes change here.
        if widget is self.mouse_over and hover_widget is self.hover_over:
            return
        super()._set_mouse_over(widget, hover_widget)


    def update_show_sessions(self) -> None:
        self.show_sessions = self.settings.ui.sessions_bar.shown(len(self.open_tabs))
