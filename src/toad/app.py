import asyncio
import json
import os
import signal
import sys
from functools import cached_property
from inspect import isabstract
from pathlib import Path
from time import monotonic
from typing import Callable, Never, TypeVar, cast

from agent_comms.execution.launch_runtime import LaunchRuntime
from agent_comms.execution.root_runtime import RootRuntime
from agent_comms.nominal.field_codec import (
    AcpSessionId,
    NoAcpSessionId,
    boundary_decoder,
)
from agent_comms.projects.checkouts import Checkout
from metaclass_registry.mro_dispatch import handles
from rich.console import RenderableType
from textual import events, on
from textual.await_complete import AwaitComplete
from textual.notifications import Notify
from textual.reactive import Required, var
from textual.signal import Signal
from textual.widget import Widget
from textual.widgets import LoadingIndicator
from textual.widgets._footer import KeyGroup
from textual.widgets.markdown import Markdown

from toad.screen_width import ScreenWidth
from toad.app_core import CorePrewarm
from toad.application_actions import ApplicationCommands
from toad.application_outcome import ApplicationOutcome, Ended, Succeeded
from toad.client.bus_selection import BusChoice, PickerRow, TailnetAnswer
from toad.clipboard import Clipboard
from toad.client.connection import CoreConnection
from toad.client.local_connection import select_connection
from toad.core import events as core_events
from toad.core import input_events
from toad.widgets.file_viewer import ImageViewer
from toad.launch_binding import AgentBinding
from toad.launch_opening import LaunchOpening, NoLaunchOpening
from toad.native_style import TransparentBackground
from toad.neovim_editing import HostsNeovim
from formbridge.forms.declared_fields import DeclaredField
from toad.setting_declarations import Effect
from toad.render_backend import Renderer, RenderTask
from toad.textual_renderers import TextualPreparedRenderer, TextualRenderProcessPool
from toad.application_lifetime import TerminalApplicationLifetime
from toad.client.application import ClientApplication
from toad.client.resource_release import AsyncResourceRelease
from toad.screens import comms, main  # noqa: F401 - register widget classes
from toad.screens.workspace import WorkspaceScreen
from toad.session_entry import TextualSessionEntry
from toad.session_scope import SessionScope
from toad.client.tab_identity import TabIdentity
from toad.terminal_attention import TerminalAttention
from toad.widgets.comms_command_dialog import ScreenCommandOrigin
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.client.application_actions import ApplicationAction
from toad.widget_actions import DeclaredWidgetActions
from toad.widgets import tool_call  # noqa: F401 - register widget classes
from toad.widgets.comms_transfer import Transfers
from toad.work_preparation import PreparationRuntime
from toad.workspace_chrome import WorkspaceChrome
from toad.workspace_sessions import (
    WorkspaceHost,
    WorkspaceSessions,
    WorkspaceSessionShutdown,
)

RenderResultT = TypeVar("RenderResultT")




class ToadLoadingIndicator(TransparentBackground, LoadingIndicator):
    """Loading shows over the widget it replaces without a tinted backdrop."""



class ApplicationNotRunningError(RuntimeError):
    """The application has no event loop to accept cross-thread work."""


class ToadApp(DeclaredWidgetActions, WorkspaceSessionShutdown, WorkspaceHost, ClientApplication, CorePrewarm, Transfers, HostsNeovim, actions=(ApplicationAction,), inherit_bindings=False):
    """The top level app."""

    COMMANDS = {ApplicationCommands}
    MODES = {"workspace": WorkspaceScreen}
    session_entries = TextualSessionEntry
    lifetime_kind = TerminalApplicationLifetime
    BINDING_GROUP_TITLE = "System"
    ALLOW_IN_MAXIMIZED_VIEW = ""

    project_dir = var[Checkout](Required())
    show_sessions = var(False)

    HORIZONTAL_BREAKPOINTS: list[tuple[int, str]] = [
        (mode, f"-{mode.name.lower()}") for mode in ScreenWidth
    ]

    PAUSE_GC_ON_SCROLL = True

    def __init__(
        self,
        agent_binding: AgentBinding,
        project_dir: Checkout,
        connection: CoreConnection,
        agent_session_id: AcpSessionId | NoAcpSessionId = NoAcpSessionId(),
        opening: LaunchOpening = NoLaunchOpening(),
    ) -> None:
        """Toad app.

        Args:
            agent_binding: The agent selected at startup.
            project_dir: Project directory.
            connection: Core transport selected by the launch owner.
        """
        self.preparation = PreparationRuntime(TextualRenderProcessPool(connection.helper_start))
        self.background_render_slots = asyncio.Semaphore(1)
        self._background_render_tasks: set[asyncio.Task[object]] = set()
        self.initialize_client(agent_binding, connection, agent_session_id, opening)
        self.clipboard_transport = Clipboard.for_platform()
        self.input_attention = TerminalAttention(self)
        self._mode_switch_lock = asyncio.Lock()

        ImageViewer.prepare_terminal()
        super().__init__()
        # Each bus listing that is mounted hears the tailnet's answers (ListsBuses).
        self.tailnet_answers: Signal[TailnetAnswer] = Signal(self, "tailnet-answers")
        self._return_value: ApplicationOutcome = Ended(self.application.version)
        self.set_reactive(ToadApp.project_dir, project_dir)

    @handles(input_events.ChangeDirectory)
    def on_change_directory(self, event: input_events.ChangeDirectory) -> None:
        try:
            project = Checkout.checked(event.path)
        except (OSError, ValueError) as error:
            self.show_error(error, "Change directory")
            return
        self.project_dir = project

    @property
    def return_value(self) -> ApplicationOutcome:
        return self._return_value

    @boundary_decoder
    def exit(
        self, result: ApplicationOutcome | None = None, return_code: int = 0,
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

    def picked_bus(self, row: PickerRow | None) -> None:
        """The picked row says what picking it does; a dismissed picker changes nothing."""
        match row:
            case PickerRow():
                row.chosen(self)

    def tailnet_answered(self, answer: TailnetAnswer) -> None:
        self.tailnet_answers.publish(answer)

    def connection_for(self, choice: BusChoice) -> CoreConnection:
        """The connection the chosen bus's launch arguments name, read as a launch reads them."""
        return select_connection(list(choice.arguments(sys.argv[1:])))

    def relaunch(self) -> None:
        running = LaunchRuntime.running()
        self.exit(Succeeded(RootRuntime.attachment(
            self.coordination_access.selection.root, running,
        ).proceed(lambda: running, lambda runtime: runtime)))


    def _make_render_processes(self):
        """Textual-owning wrapper: a Textual consumer owns its message pump and Worker,
        so detached work never borrows those contexts (`TextualOwners`)."""
        return TextualPreparedRenderer(self.preparation)

    async def _close_all(self) -> None:
        # View release can fail. The application still owns its observation
        # pipe and process pools; an Unmount event may never follow that error.
        async with AsyncResourceRelease() as release:
            release.push_async_callback(self.close_background_render_tasks)
            release.callback(self.input_attention.close)
            release.callback(self.colours.stop)
            release.push_async_callback(self.close_client)

    def begin_frontend(self) -> None:
        # Mount runs inside Textual's batch, which draws no frame, and restored
        # tabs wait for drawn frames, so start runs beside mount, never inside it.
        self.application.begin()

    async def close_native_views(self) -> None:
        """Textual closes its screens and widgets, which release their views."""
        await super()._close_all()

    async def close_rendering(self) -> None:
        await self.render_processes.aclose()

    async def close_background_render_tasks(self) -> None:
        """Join accepted render work even when an earlier release failed."""
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


    def settings_widgets(self, widget_type):
        roots = (*self.workspace_sessions.views.values(), *self.screen_stack)
        return {widget for root in roots for widget in root.walk_children(widget_type)}

    # Textual overrides of the hamburger capabilities declared on ClientApplication.
    # The default notice stays on the base so a Qt frontend still gets the menu item.

    def open_bus_switcher(self) -> None:
        from toad.screens.bus_choice import BusChoices
        self.push_screen(BusChoices(), self.picked_bus)

    async def edit_settings(self) -> None:
        self.run_worker(self._edit_settings_worker)

    async def _edit_settings_worker(self) -> None:
        from toad.screens.settings import SettingsScreen
        await self.push_screen_wait(SettingsScreen())
        await self.saved_settings.save()

    async def open_team_board(self) -> None:
        from toad.screens.team import TeamPage
        self.push_screen(TeamPage())

    async def open_keymap_browser(self) -> None:
        from toad.keymap import KeyInvocationId
        from toad.screens.keymap import KeymapScreen
        focused = frozenset(
            KeyInvocationId(invocation.key_identity())
            for node, bindings in self.screen._binding_chain
            for _key, binding in bindings if binding.state(self, node)
            for invocation in binding.invocations()
        )
        self.push_screen(KeymapScreen(focused))

    @property
    def welcome_hints(self) -> str:
        """Textual welcome hint line: keyboard shortcuts.
        Content preserved from `WelcomeScreen.HINTS` at
        `src/toad/screens/welcome.py:242`; moved onto the app so Qt's
        welcome can read the same contract via `self.app.welcome_hints`
        and supply its own gesture string."""
        return (
            "[b]n[/b] new session   [b]ctrl+g[/b] channel view   [b]ctrl+b[/b] sidebar\n"
            "[b]↑ ↓[/b] choose   [b]enter[/b] open"
        )

    def ensure_settings_file(self) -> None:
        settings = self.saved_settings
        path = settings.path()
        if not path.exists():
            settings.save_sync(force=True)
            if path.is_file():
                self.notify(f"Wrote default settings to {path}", title="Settings")

    def publish_clipboard(self, text: str) -> None:
        self.clipboard_transport = self.clipboard_transport.publish(self, text)


    @on(Notify)
    def on_notify(self, event: Notify) -> None:
        self.input_attention.notification(event.notification)

    def get_loading_widget(self) -> Widget:
        return ToadLoadingIndicator()

    def make_opening_view(self, request, origin, identity):
        """Textual's thread-navigation opening view: a `MainScreen` in opening state.
        Imported here (not at module top, not from `ThreadOpening`) so Qt's
        `ThreadOpening.__init__` never has to reach `toad.screens.main` and the
        Textual-widget pyramid it imports (textual_colours, watchdog, ...)."""
        from toad.screens.main import MainScreen
        return MainScreen.opening(request, origin, self)

    def thread_view(self, prepared):
        from toad.screens.main import MainScreen
        return MainScreen.from_thread(prepared.project, prepared.root,
                                      prepared.thread.incarnation, self.agent_binding)

    def replace_opening_view(self, opening_view, prepared, identity):
        """Textual's `MainScreen` handles both opening and bound lifecycle phases on
        the same instance — `prepared.bind(view)` updates state in place, no swap
        needed. Return the opening_view unchanged so `ThreadOpening.mount` keeps
        driving the same widget. Qt's override is the one that does the real
        swap: see `QtToadApp.replace_opening_view`."""
        return opening_view

    def _handle_exception(self, error: Exception) -> bool:
        """The mounted application owns escaped handler and worker errors."""
        if not self.screen_stack or not self.screen.is_mounted:
            return super()._handle_exception(error)
        self.show_error(error, type(error).__name__)
        return True

    @on(events.Load)
    async def on_load(self) -> None:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, self.exit)
        asyncio.get_running_loop().add_signal_handler(signal.SIGUSR1, self.relaunch)
        self._prewarm_conversation_css()
        self._prewarm_core_modules()
        db = await self.get_db()
        await db.create()
        self.ensure_settings_file()
        self.colours.start()
        self.saved_settings.apply_all()

    def _prewarm_conversation_css(self) -> None:
        """Load known conversation classes' default CSS in one parse.

        The classes are discovered through their ordinary inheritance rather
        than maintaining a manual list of every channel, tool and Markdown
        component. Registration deduplicates identical sources when widgets
        eventually mount, avoiding a full CSS rebuild of already-open tabs.
        """
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


    async def prepare_session(self, mode: str) -> SessionScope:
        """Mount an owner shell under the same admission as visible transitions."""
        async with self._mode_switch_lock:
            return await self.workspace_sessions.prepare(mode)

    def select_session(self, mode: str) -> AwaitComplete:
        """A person's selection: its visit is recorded once the tab is shown."""
        return self._switch(mode, self.tab_order.record_visit)

    def show_history_step(self, mode: str) -> AwaitComplete:
        """A history step: TabOrder recorded its visit when the step was taken."""
        return self._switch(mode, lambda identity: None)

    def _switch(self, mode: str, visited: Callable[[TabIdentity], object]) -> AwaitComplete:
        if mode != self.selected_mode:
            self.navigation_reader.invalidate()
        return AwaitComplete(self._switch_mode_ready(mode, visited))

    async def _switch_mode_ready(self, mode: str, visited: Callable[[TabIdentity], object]) -> None:
        async with self._mode_switch_lock:
            previous = self.selected_mode
            # Source retirement and native preparation may await I/O,
            # child pumps or compensated layout. Their original owners
            # fence those mutations; holding a global paint batch here
            # also withholds the frames those operations may need.
            if self.current_mode != "workspace":
                await super().switch_mode("workspace")
            # A switch is several frames of work: hold the workspace's
            # frames and let the loop run due input and timers between steps, so input is
            # never held behind the whole switch and no half-switched
            # scene is written. Layout still runs for steps that measure.
            # Releasing the hold repaints the screen it held, however the switch ends.
            with self.workspace_screen.hold_frames():
                await self.workspace_sessions.select(mode)
                await self.workspace_screen.prepare_navigation()
                await self.workspace_screen.layout_navigation()
            if mode != previous:
                if entry := self.session_navigation.get(mode):
                    visited(entry.identity)
                self.events.publish(core_events.SessionSelected(mode, previous))


    @cached_property
    def workspace_chrome(self):
        return WorkspaceChrome(self)

    @cached_property
    def workspace_sessions(self):
        return WorkspaceSessions(self)

    @property
    def workspace_screen(self):
        return self.get_screen_stack("workspace")[0]

    @property
    def selected_session(self):
        return self.workspace_sessions.source.view

    def capture_command_origin(self) -> ScreenCommandOrigin:
        return ScreenCommandOrigin(self.screen)

    def open_channel_sort(self, channel: str) -> None:
        group = self.workspace_chrome.channels.roster.groups[channel]
        self.run_worker(group.sort_choice.open_sort(), group="sort-order")

    async def reveal_sidebar(self) -> bool:
        sidebar = self.screen.query_one_optional(CommsSidebar)
        if sidebar is None:
            return False
        sidebar.query_ancestor(SideBar).reveal()
        sidebar.query_ancestor(SideBarCollapsible).collapsed = False
        await sidebar.navigation.focus_current()
        return True

    @property
    def selected_mode(self):
        return (self.workspace_sessions.source.identity
                if self.current_mode == "workspace" else self.current_mode)

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

    @on(events.Mount)
    async def on_mount(self) -> None:
        # The terminal driver is running now, so ANSI themes can query its colours.
        await self.colours.mount()
        self.start_client()
        from toad.keymap import report_broken_keymap
        report_broken_keymap(self)
        # Background threads (Core reads, preparation) give the GIL back to
        # the UI thread within 1 ms instead of the default 5 ms.
        sys.setswitchinterval(0.001)

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
        """A right-click offers the drawn action's menu before the click's own action."""
        if (isinstance(event, events.Click) and event.button == 3
                and await handler.action.secondary(self, default_namespace, event)):
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


    def show_session_tabs(self, shown: bool) -> None:
        """Textual's tab labels draw the open tabs again on the next sidebar presentation."""
        self.show_sessions = shown

    def follow_wheel_scroll_rows(self) -> None:
        self.scroll_sensitivity_y = self.settings.ui.wheel_scroll_rows

    def follow_theme(self) -> None:
        self.colours.choose(self.settings.ui.theme)

    def follow_key_mode(self) -> None:
        from toad.widgets.prompt import PromptTextArea
        for editor in self.settings_widgets(PromptTextArea):
            editor.apply_keyboard_profile()
        self.refresh_bindings()

    def follow_keymap(self) -> None:
        self.set_keymap(self.settings.ui.keymap.native())

    def follow_line_renderer(self) -> None:
        self.colours.refresh_line_renderer()
        self.theme_changed_signal.publish(self.current_theme)


# Screens that declare keys but open lazily: loaded with the app, after it (they import from
# it), so the keymap catalog lists their keys before they first open. The catalog reads
# loaded declarations; it walks no package.
from toad.screens import keymap, mcp_decision, permissions, settings  # noqa: E402, F401
from toad.widgets import context_explorer  # noqa: E402, F401
