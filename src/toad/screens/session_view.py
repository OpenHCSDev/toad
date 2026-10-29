"""Logical session surfaces hosted by the one native WorkspaceScreen."""

from textual.containers import Vertical
from textual.geometry import Region
from textual.reactive import reactive
from contextlib import contextmanager
from metaclass_registry.mro_dispatch import handles
from toad.core.events import ThreadIdentityChanged
from toad.core.source_events import TranscriptSourceWorkFinished
from toad.core_event_carrier import CoreEventMessage, CoreEventReceiver
from toad.thread_identity import SessionIdentity, NoThreadIdentity
from toad.session_scope import NoSessionOrigin, SessionOrigin, SessionScope
from toad.navigation_target import NavigationTarget, NoTarget
from toad.widget_actions import DeclaredWidgetActions
from toad.widgets.message_notifications import (
    NothingToRead,
    PaintedRead,
    VisibleReadMarking,
)


class SessionView(DeclaredWidgetActions, VisibleReadMarking, CoreEventReceiver, Vertical, SessionScope):
    title = reactive("")
    sub_title = reactive("")

    DEFAULT_CSS = "SessionView { width: 1fr; height: 1fr; }"

    def __init__(self, *args, **kwargs):
        self._identity: SessionIdentity = NoThreadIdentity()
        super().__init__(*args, **kwargs)

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

    def belongs_to_wire(self, root) -> bool:
        """Unbound views may project the selected wire; bound views stay on it."""
        from pathlib import Path

        source = self.coordination_root
        return source is None or Path(source).expanduser().resolve() == root

    def read_visible(self) -> PaintedRead:
        """Views without a conversation have no native transcript to mark read."""
        return NothingToRead()

    async def wait_content_ready(self) -> None:
        """A view composed with its content is ready once mounted; loading views override this."""

    def message_region(self) -> Region | None:
        """The scrolling message viewport of this view's conversation, in screen cells;
        none before its conversation mounts, and none in views without one."""
        from toad.widgets.conversation import Conversation

        conversation = self.query_one_optional(Conversation)
        if conversation is None or not conversation.is_mounted:
            return None
        return conversation.window.scrollable_content_region

    def history_painted(self) -> None:
        """Only the session on screen reads what it painted; hidden tabs stay unread."""
        if self.is_current:
            self.mark_visible()

    @handles(TranscriptSourceWorkFinished)
    def on_transcript_source_work_finished(self, event: TranscriptSourceWorkFinished, message: CoreEventMessage) -> None:
        message.stop()
        self.history_painted()

    async def open_direct_messages(self) -> None:
        """Open this session's direct-message destination when it has one."""
        self.notify(
            "Direct messages are unavailable from this view", title="Direct messages"
        )

    def sidebars(self):
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
