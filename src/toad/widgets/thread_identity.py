"""Panels read identity from their logical session, not the native workspace."""
from agent_comms.mro_dispatch import handles
from textual.widget import Widget

from toad.core.events import ThreadIdentityChanged
from toad.core_event_carrier import CoreEventReceiver
from toad.thread_identity import ThreadIdentity


class ShowsThreadIdentity(CoreEventReceiver, Widget):
    @property
    def thread_view(self):
        from toad.screens.session_view import SessionView

        return self.query_ancestor(SessionView)

    @property
    def thread_identity(self) -> ThreadIdentity:
        return self.thread_view.thread_identity

    def _on_mount(self) -> None:
        self.observe_core(self.thread_view.core_publications)
        self.identity_changed(self.thread_identity)

    @handles(ThreadIdentityChanged)
    def thread_identity_changed(self, event: ThreadIdentityChanged) -> None:
        self.identity_changed(self.thread_identity)

    def identity_changed(self, identity: ThreadIdentity) -> None:
        raise NotImplementedError
