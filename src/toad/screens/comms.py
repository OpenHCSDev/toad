import asyncio
from functools import partial
from typing import Literal

from agent_comms.messaging.historical_views import (
    AllHistoricalSenders,
    NamedHistoricalSender,
)
from agent_comms.projects.checkouts import Checkout
from metaclass_registry.mro_dispatch import handles
from textual import on
from textual.app import ComposeResult
from textual.document._editing import EditingMode
from textual.events import Mount
from textual.widgets import Static
from textual.worker import WorkerCancelled

from toad.app_node import ToadNode
from toad.constants import WELCOME
from toad.conversation_capabilities import ConversationNavigation
from toad.conversation_kind import ConversationKind
from toad.core import session_requests
from toad.core.input_events import SelectHistoricalIdentity
from toad.core_event_carrier import CoreEventMessage
from toad.navigation_context import NavigationContext
from toad.navigation_target import (
    FeedTarget,
    HistoryTarget,
    NavigationTarget,
    SelectTarget,
)
from toad.project_path_owner import CheckoutRoot
from toad.screens.historical_sessions import HistoricalSessions
from toad.screens.session_view import SessionBody, SessionContents, SidebarSessionView
from toad.session_actions import CloseViewAction, ReturnToViewAction
from toad.session_scope import NoSessionOrigin
from toad.thread_identity import SessionIdentity
from toad.widget_actions import CyclesSessions, TogglesIrc, WidgetAction
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.session_thread_sidebar import ConversationThreadSidebar
from toad.widgets.side_bar import SideBar, ThreadSidebar
from toad.worker_group import WorkerGroup


class CommsContentLoad(WorkerGroup):
    """Loads the conversation content once a route frame is written."""



class ViewAction(WidgetAction, affix="Action"):
    pass


class SavedSessionsAction(ViewAction):
    title = 'Saved sessions'
    keys = {EditingMode: ('f8',)}
    priority = True
    show = True

    async def apply(self, context: CommsScreen) -> None:
        observed = context.app.coordination_access.observation.observed()
        threads = await asyncio.to_thread(observed.historical_threads, AllHistoricalSenders())
        if not threads:
            context.notify("No preserved history sources are attached yet.")
            return
        context.app.push_screen(
            context.conversation.historical_sessions(
                partial(HistoricalSessions, observed, threads),
                context.app.coordination_access.observation.observed()
                .sidebar.observation.thread_names(),
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


class CommsScreen(ConversationNavigation, TogglesIrc, CyclesSessions, CheckoutRoot, SidebarSessionView[ThreadSidebar], ToadNode, can_focus=False,
                  actions=(ViewAction, ReturnToViewAction, CloseViewAction)):
    """A channel or DM represented as a native concurrent Toad session."""

    AUTO_FOCUS = "CommsChatView Prompt TextArea"
    def __init__(
        self,
        *,
        project_path: Checkout,
        me: str,
        conversation: ConversationKind,
        wire_root: str,
    ) -> None:
        super().__init__()
        self.project_path = project_path
        self._identity = SessionIdentity.for_thread(me, wire_root)
        self.conversation = conversation
        self.wire_root = wire_root
        self._content_ready = asyncio.Event()
        self._content_error: BaseException | None = None
        self._content_loaded = False


    @property
    def coordination_root(self) -> str | None:
        return self.wire_root

    @property
    def origin(self) -> NoSessionOrigin:
        """A conversation tab belongs to no session, so it has no session transcript."""
        return NoSessionOrigin(self.id or "conversation tab")

    @property
    def navigation_target(self) -> NavigationTarget:
        return HistoryTarget.for_conversation(
            self.conversation,
            self.app.coordination_access.observation.observed()
            .sidebar.observation.thread_names(),
        )



    def make_thread_sidebar(self):
        return ConversationThreadSidebar(self, self.conversation.sidebar_threads())

    def compose(self) -> ComposeResult:
        content = (
            (self.create_chat(),)
            if self._content_loaded
            else (
                Static(f"Opening {self.conversation.initial_label}…"),
            )
        )
        yield SessionBody(
            self.thread_sidebar,
            SessionContents(*content),
        )

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
        observed = self.app.coordination_access.observation.observed()
        threads = await asyncio.to_thread(
            observed.historical_threads, NamedHistoricalSender(event.name)
        )
        if not threads:
            self.notify("This sender has no preserved identity declaration.")
            return
        self.app.push_screen(
            HistoricalSessions(
                observed, threads, name=event.name, source=event.source
            )
        )


    @on(Mount)
    def on_mount(self) -> None:
        if not self._content_loaded:
            self.screen.frame_presentation.defer(self, self._start_hydration)
            return
        self._prepare_content()

    def _start_hydration(self) -> None:
        """Only a written route frame may start conversation composition."""
        if not self._content_loaded:
            CommsContentLoad.run_on(self, self._load_content)

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
            content = self.query_one(SessionContents)
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
        for worker in CommsContentLoad.cancel_all(self):
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
        # Threads opened from a conversation tab attach to home: no session owns this tab.
        return NavigationContext(
            self.app,
            WELCOME,
            self.project_path,
            self.thread_identity.thread_name(),
        )

    async def open_sidebar_target(self, target: NavigationTarget) -> None:
        """Navigation from a conversation tab is home's: home is prepared as the origin first."""
        home = await self.app.prepare_session(WELCOME)
        await home.origin.require().prepare_history_origin()
        await super().open_sidebar_target(target)

    @handles(SelectTarget)
    async def on_select_target(self, event: SelectTarget) -> None:
        await self.open_sidebar_target(event.target)


    async def show_feed(self) -> None:
        await self.open_sidebar_target(FeedTarget())

    async def return_to_view(self) -> None:
        await ReturnToViewAction().apply(self)

    async def show_direct_messages(self) -> None:
        await self.return_to_view()
        self.app.session_navigation.direct_messages()

    async def toggle_irc(self) -> None:
        await self.conversation.toggle_irc(self)

    async def open_direct_messages(self) -> None:
        await self.conversation.toggle_dm(self)

    def navigate_session(self, direction: Literal[-1, 1]) -> None:
        self.app.session_navigation.events.publish(
            session_requests.SessionNavigate(direction)
        )
