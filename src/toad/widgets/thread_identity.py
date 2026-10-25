"""Panels read identity from their logical session, not the native workspace."""

from agent_comms.mro_dispatch import handles
from textual.widget import Widget

from toad.core.events import ThreadIdentityChanged
from toad.core_event_carrier import CoreEventReceiver
from toad.session_scope import SessionScope
from toad.thread_identity import SessionIdentity


class ShowsThreadIdentity(CoreEventReceiver, Widget):
    @property
    def thread_view(self) -> SessionScope:
        return self.query_ancestor(SessionScope)

    def _on_mount(self) -> None:
        self.observe_core(self.app.events)
        self.identity_changed(self.thread_view.thread_identity)

    @handles(ThreadIdentityChanged)
    def thread_identity_changed(self, event: ThreadIdentityChanged) -> None:
        if event.view is self.thread_view:
            self.identity_changed(event.view.thread_identity)

    def identity_changed(self, identity: SessionIdentity) -> None:
        raise NotImplementedError
