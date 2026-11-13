"""Logical session surfaces hosted by the one native WorkspaceScreen."""

from abc import abstractmethod
from functools import cached_property
from textual.containers import Center, Vertical
from textual.view import FILL, WidgetView
from textual.color import Color
from textual.layout import Layout
from toad.configured_view import ConfiguredView
from toad.settings_scope import ConversationSettingsScope
from ui_theme.scheme import BackgroundColour
from textual.reactive import reactive
from contextlib import contextmanager
from pathlib import Path
from metaclass_registry.mro_dispatch import handles
from toad.core.events import ThreadIdentityChanged
from toad.layout_preferences import FollowsLayoutPreferences
from toad.core.source_events import TranscriptSourceWorkFinished
from toad.core_event_carrier import CoreEventMessage, CoreEventReceiver
from toad.thread_identity import SessionIdentity, NoThreadIdentity
from toad.session_scope import NoSessionOrigin, SessionOrigin, SessionScope
from toad.navigation_context import NavigationOwner
from toad.navigation_target import NavigationTarget, NoTarget
from toad.app_node import ToadNode
from toad.session_tracker import SidebarState
from toad.widgets.side_bar import SideBar, ThreadSidebar
from toad.widget_actions import DeclaredWidgetActions
from toad.widgets.message_notifications import (
    NothingToRead,
    PaintedRead,
    VisibleReadMarking,
)
from textual.events import Mount
from textual import on


class SessionView(
    DeclaredWidgetActions,
    VisibleReadMarking,
    CoreEventReceiver,
    Vertical,
    SessionScope,
):
    title = reactive("")
    sub_title = reactive("")

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = self.styles.height = FILL

    # The absent identity is an immutable value; concrete bindings replace it
    # on the instance. Native construction stays with Vertical/Widget.
    _identity: SessionIdentity = NoThreadIdentity()

    def close_core_events(self) -> None:
        """Retire this logical source's descendants before its tab entry disappears."""
        for receiver in self.query().results(CoreEventReceiver):
            receiver.close_core_events()
        super().close_core_events()

    @property
    def display_name(self) -> str:
        """Borrow this view's current label from the same projection as its tab."""
        sessions = self.app.session_navigation
        return self.app.coordination_access.observation.tab(
            sessions.get(self.id), sessions
        ).title

    @property
    def is_current(self) -> bool:
        return self.app.workspace_sessions.owns(self) and self.screen.is_current

    @property
    def coordination_root(self) -> str | None:
        return self._identity.wire_root()

    @property
    def origin(self) -> SessionOrigin:
        """What a session or history requested from this view starts from."""
        return NoSessionOrigin(str(self))

    @property
    def navigation_target(self) -> NavigationTarget:
        return NoTarget()

    def belongs_to_wire(self, root: Path) -> bool:
        """Unbound views may project the selected wire; bound views stay on it."""
        return self._identity.belongs_to_wire(root)

    def read_visible(self) -> PaintedRead:
        """Views without a conversation have no native transcript to mark read."""
        return NothingToRead()

    async def wait_content_ready(self) -> None:
        """A view composed with its content is ready once mounted; loading views override this."""

    def history_painted(self) -> None:
        """Only the session on screen reads what it painted; hidden tabs stay unread."""
        if self.is_current:
            self.mark_visible()

    @handles(TranscriptSourceWorkFinished)
    def on_transcript_source_work_finished(self, event: TranscriptSourceWorkFinished, message: CoreEventMessage) -> None:
        message.stop()
        self.history_painted()

    def sidebars(self) -> tuple[SideBar, ...]:
        """Supply this view's native sidebar resources through its declaration."""
        return ()

    def keyboard_scopes(self) -> tuple[DeclaredWidgetActions, ...]:
        """A source adds its loaded reader/composer through its own lifecycle."""
        return (self,)

    @property
    def thread_identity(self) -> SessionIdentity:
        return self._identity

    @contextmanager
    def changing_identity(self):
        previous = self.thread_identity
        try:
            yield previous
        finally:
            if previous != self.thread_identity:
                self.identity_changed(previous)
                self.app.events.publish(ThreadIdentityChanged(self))

    def identity_changed(self, previous: SessionIdentity) -> None:
        """A source may synchronize its dependent sessions after a real change."""

    def activate_session(self) -> None:
        """Bind surface-local observers before its selected frame."""

    async def prepare_navigation(self) -> bool:
        """Reconcile only this logical source's sidebar navigation and observers."""
        from toad.widgets.side_bar import SideBarCollapsible

        changed = False
        for sidebar in self.sidebars():
            panels = tuple(sidebar.query(SideBarCollapsible))
            before = tuple(panel.collapsed for panel in panels)
            changed |= sidebar.restore_navigation()
            changed |= before != tuple(panel.collapsed for panel in panels)
            sidebar.schedule_hydration()
        return changed

    async def prepare_presentation(self) -> None:
        """Restore source-bound rich presentation for the selected logical view."""
        from toad.widgets.history_anchor import HistoryWindow

        for window in self.query(HistoryWindow):
            window.request_preparation()

    async def retire_presentation(self) -> None:
        """Release rich presentation without stopping its operational sources."""
        from toad.widgets.history_anchor import HistoryWindow
        from toad.widgets.conversation import Conversation

        for conversation in self.query(Conversation):
            conversation.window.park_reader(conversation.contents)
        # Clear focus before hiding any native resource;
        # shared chrome retains its independently owned focus.
        if self.has_focus_within:
            self.screen.set_focus(None)
        for window in self.query(HistoryWindow):
            window.retire_presentation_wait()
            window.settle_preparation()

    async def close_presentation(self) -> None:
        """Views without retained operational sources need no domain finalization."""

    def retained_native_presentations(self):
        """Declare accepted native trees; non-native views own no such trees."""
        return ()


class SessionBody(WidgetView, ToadNode, Center):
    """The shared sidebar/content layout reads its owner directly."""

    width = height = FILL
    align_horizontal = "center"

    @property
    def child_layout(self) -> Layout:
        return self.app.workspace_chrome


class SessionContents(WidgetView, FollowsLayoutPreferences, ToadNode, Vertical):
    """The conversation fills the space beside the retained sidebar."""

    width = height = FILL

    @on(Mount)
    def on_mount(self) -> None:
        self.apply_layout_preferences()

    def apply_layout_preferences(self) -> None:
        """Place a width-constrained conversation where the column alignment setting puts it."""
        self.align_horizontal = self.settings.ui.column_alignment.horizontal
        self.refresh(layout=True)


class SidebarSessionView[SidebarT: ThreadSidebar](ConfiguredView, ConversationSettingsScope, WidgetView, NavigationOwner, SessionView):
    """One session-owned sidebar survives construction, mounting and retirement.

    Composition mounts this resource; it does not create its identity. Chrome
    may ask for membership before the native tree exists, and close still owns
    the same resource after it has left that tree.
    """

    width = height = FILL
    layer_order = ("sidebar", "screen", "base")

    @property
    def paint_background(self) -> Color:
        return self.app.color_system.color(BackgroundColour.name)

    @cached_property
    def _thread_sidebar_state(self) -> SidebarState:
        return SidebarState()

    @abstractmethod
    def make_thread_sidebar(self) -> SidebarT: ...


