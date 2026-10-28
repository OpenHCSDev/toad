from metaclass_registry.mro_dispatch import handles
from toad.core_event_carrier import CoreEventMessage
from toad.core import events as core_events
from toad.core import session_requests
from toad.screens.session_view import SessionView
from toad.project_path_owner import CheckoutRoot
import asyncio
from functools import partial
from pathlib import Path
from typing import Literal
from agent_comms.repo import Checkout

from textual import containers, on
from textual.app import ComposeResult
from textual.document._editing import EditingMode
from toad.session_actions import ReturnToViewAction, CloseViewAction
from toad.widget_actions import WidgetAction, TogglesIrc, CyclesSessions
from textual.events import ScreenResume
from textual.worker import WorkerCancelled
from textual.widgets import Static

from toad import messages
from toad.conversation_kind import ConversationKind
from toad.widgets.comms_chat import CommsChatView
from toad.core.input_events import SelectHistoricalIdentity
from toad.core.input_events import SelectTarget
from toad.widgets.comms_sidebar import CoordinationStatus, CommsSidebar
from toad.session_tracker import SidebarState
from toad.navigation_context import NavigationContext
from toad.navigation_target import HistoryTarget, NavigationTarget
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import SideBar, ThreadSidebar, TabHistoryControls
from toad.widgets.thread_comms import RelationshipSort, ThreadCommsSidebar
from toad.app_node import ToadNode


class ViewAction(WidgetAction, affix="Action"):
    pass


class SavedSessionsAction(ViewAction):
    title = 'Saved sessions'
    keys = {EditingMode: ('f8',)}
    priority = True
    show = True

    async def apply(self, context: CommsScreen) -> None:
        from toad.screens.historical_sessions import HistoricalSessions

        comms = context.app.coordination_access.observation.observed().service
        threads = await asyncio.to_thread(comms.views.historical_threads)
        if not threads:
            context.notify("No preserved history sources are attached yet.")
            return
        context.app.push_screen(
            context.conversation.historical_sessions(
                partial(HistoricalSessions, comms, threads),
                context.app.coordination_access.observation.observed()
                .sidebar.observation.require_snapshot().references,
            )
        )


class MessageStyleAction(ViewAction):
    title = 'IRC / Markdown'
    keys = {EditingMode: ('ctrl+t',)}
    show = True

    def apply(self, context: CommsScreen) -> None:
        if chat := context.query_one_optional(CommsChatView):
            history = chat.message_history
            history.run_worker(history.toggle_style, group="message-style")


class FocusPromptAction(ViewAction):

    def apply(self, context: CommsScreen) -> None:
        if chat := context.query_one_optional(CommsChatView):
            chat.prepare_prompt()


class CommsScreen(TogglesIrc, CyclesSessions, CheckoutRoot, SessionView, ToadNode, can_focus=False,
                  actions=(ViewAction, ReturnToViewAction, CloseViewAction)):
    """A channel or DM represented as a native concurrent Toad session."""

    AUTO_FOCUS = "CommsChatView Prompt TextArea"
    CSS_PATH = ["main.tcss", "comms.tcss"]
    def __init__(
        self,
        *,
        project_path: Checkout,
        owner_mode: str,
        me: str,
        conversation: ConversationKind,
        owner_root: str | None = None,
        wire_root: str | None = None,
    ) -> None:
        super().__init__()
        self.project_path = project_path
        self.owner_mode = owner_mode
        from toad.thread_identity import SessionIdentity

        self._identity = SessionIdentity.for_thread(me, owner_root)
        self.conversation = conversation
        self.wire_root = wire_root
        self._thread_sidebar_state = SidebarState()
        self._content_ready = asyncio.Event()
        self._content_error: BaseException | None = None
        self._content_loaded = False


    @property
    def coordination_root(self) -> str | None:
        return self.wire_root

    @property
    def origin(self):
        return self.app.workspace_sessions.origin(self.owner_mode)

    @property
    def navigation_target(self) -> NavigationTarget:
        return HistoryTarget.for_conversation(
            self.conversation,
            self.app.coordination_access.observation.observed()
            .sidebar.observation.require_snapshot().references,
        )

    def rebind_identity(self, identity: str) -> None:
        with self.changing_identity():
            self._identity = self.thread_identity.with_thread(identity)
            if chat := self.query_one_optional(CommsChatView):
                chat._me = identity

    def rebind_owner_root(self, root: str | None) -> None:
        with self.changing_identity():
            self._identity = self.thread_identity.with_root(root)

    def rebind_project(self, project: Checkout) -> None:
        changed = project != self.project_path
        self.project_path = project
        if changed:
            self.link_context_changed()
        if chat := self.query_one_optional(CommsChatView):
            chat.project_path = project
            chat.working_directory = str(project)

    def sidebars(self):
        sidebar = self.query_one_optional(ThreadSidebar)
        return (sidebar,) if sidebar is not None else ()

    def compose(self) -> ComposeResult:
        content = (
            (self.create_chat(),)
            if self._content_loaded
            else (
                Static(f"Opening {self.conversation.initial_label}…", id="comms-opening"),
            )
        )
        yield containers.Center(
            ThreadSidebar(
                SideBar.Panel(
                    "Connection",
                    CoordinationStatus(),
                    id="coordination-panel",
                ),
                SideBar.Panel(
                    "Comms",
                    ThreadCommsSidebar(),
                    id="thread-comms-panel",
                    header_control=RelationshipSort(),
                ),
                state=self._thread_sidebar_state,
            ),
            containers.Vertical(*content, id="comms-content"),
        ).set_styles(layout=self.app.workspace_chrome)

    def create_chat(self) -> CommsChatView:
        """One route-bound conversation factory for compose and lazy hydration."""
        return CommsChatView(
            self.project_path,
            me=self.thread_identity.thread_name(),
            conversation=self.conversation,
            wire_root=self.wire_root,
        )

    @handles(SelectHistoricalIdentity)
    async def select_historical_identity(self, event: SelectHistoricalIdentity, message: CoreEventMessage) -> None:
        message.stop()
        from toad.screens.historical_sessions import HistoricalSessions

        comms = self.app.coordination_access.observation.observed().service
        threads = await asyncio.to_thread(
            comms.views.historical_threads, event.name
        )
        if not threads:
            self.notify("This sender has no preserved identity declaration.")
            return
        self.app.push_screen(
            HistoricalSessions(
                comms, threads, name=event.name, source=event.source
            )
        )


    def on_mount(self) -> None:
        if not self._content_loaded:
            self.screen.frame_presentation.defer(self, self._start_hydration)
            return
        self._prepare_content()

    def _start_hydration(self) -> None:
        """Only a written route frame may start conversation composition."""
        if not self._content_loaded:
            self.run_worker(self._load_content, group="comms-content")

    def _prepare_content(self) -> None:
        self.observe_core(self.app.events)
        chat = self.query_one(CommsChatView)
        chat._me = self.thread_identity.thread_name()
        chat.project_path = self.project_path
        # Shared navigation may already belong to another tab when hydration
        # finishes. Its actor/target are bound by the mode transition owner.
        chat.prepare_prompt()

    async def _load_content(self) -> None:
        if self._content_loaded or not self.is_attached:
            return
        self._content_loaded = True
        try:
            # The navigation/sidebar shell is already visible in its chosen
            # state. Hydrate only the conversation; retain those exact controls
            # and their scroll position throughout the opening transition.
            content = self.query_one("#comms-content", containers.Vertical)
            await content.remove_children()
            await content.mount(self.create_chat())
            if self.is_attached:
                self._prepare_content()
                if self.is_current:
                    await self.screen.prepare_navigation()
                    await self.screen.layout_navigation()
        except BaseException as error:
            self._content_error = error
            raise
        finally:
            self._content_ready.set()

    async def wait_content_ready(self) -> None:
        await self._content_ready.wait()
        if self._content_error is not None:
            raise self._content_error

    async def close_presentation(self) -> None:
        """Join hydration before its controls or input pump are pruned."""
        for worker in self.workers.cancel_group(self, "comms-content"):
            try:
                await worker.wait()
            except WorkerCancelled as error:
                self._content_error = error
        self._content_ready.set()

    def activate_session(self) -> None:
        if chat := self.query_one_optional(CommsChatView):
            self.call_after_refresh(chat.prepare_prompt)



    def focus_sidebar_return(self) -> None:
        if chat := self.query_one_optional(CommsChatView):
            target = chat.prompt.prompt_text_area
            if target.focusable:
                self.screen.set_focus(target, scroll_visible=False)

    @on(SideBar.Dismiss)
    def on_side_bar_dismiss(self, event: SideBar.Dismiss) -> None:
        event.stop()
        FocusPromptAction().apply(self)

    @property
    def navigation_context(self) -> NavigationContext:
        return NavigationContext(
            self.app,
            self.owner_mode,
            self.project_path,
            self.thread_identity.thread_name(),
        )

    @handles(SelectTarget)
    async def on_select_target(self, event: SelectTarget) -> None:
        await self.open_sidebar_target(event.target)


    async def toggle_irc(self) -> None:
        await self.conversation.toggle_irc(self)

    async def open_direct_messages(self) -> None:
        await self.conversation.toggle_dm(self)

    def navigate_session(self, direction: Literal[-1, 1]) -> None:
        self.app.session_navigation.events.publish(
            session_requests.SessionNavigate(self.owner_mode, direction)
        )
