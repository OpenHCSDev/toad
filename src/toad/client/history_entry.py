"""The owner's tab for one bus conversation, shared by every frontend.

The entry owns the conversation's identity, the threads and channels it was opened
over, its address and how its tab is labelled. A native member adds only the view it
builds: Textual a CommsScreen, Qt a conversation widget.
"""

from __future__ import annotations

from agent_comms.messaging.display_references import (
    CurrentDisplayReferences,
    ReferenceContext,
)
from agent_comms.projects.checkouts import Checkout
from metaclass_registry.mro_dispatch import handles

from toad.client.connection import Observing
from toad.client.conversation import CommsViewKey
from toad.navigation_preparation import CommsNavigation
from toad.client.session_entry import SessionEntry
from toad.client.session_tracker import ConversationTab, NamedTab, OpenTab
from toad.client.tab_identity import TabIdentity, TabTargetGone
from toad.client.tab_identity.kinds import CommsTab
from toad.core.projection import MroProjection
from toad.session_host import SessionNavigator
from toad.thread_identity import SessionIdentity


class HistorySessionEntry(SessionEntry, MroProjection[OpenTab], declared_name=None):
    """The shared conversation entry in Toad's workspace; a frontend's member builds its view."""

    def __init__(self, identity: TabIdentity, opened: CommsNavigation, project: Checkout) -> None:
        """The owner's tab for one conversation; no session owns it, so none closes or returns it."""
        super().__init__(identity)
        self.key, self.viewer, self.participants = opened.key, opened.viewer, opened.participants
        self.project = project

    @property
    def viewer_identity(self):
        """The viewer as a thread on the conversation's wire: who the tab acts as."""
        return SessionIdentity.for_thread(self.viewer, self.key.root)

    @staticmethod
    def reopened(identity: CommsTab, observed: Observing, project: Checkout) -> CommsNavigation:
        """A conversation tab read again on the bus that owns it, as its viewer."""
        if not observed.observes(identity.root):
            raise TabTargetGone(identity, f"History belongs to another bus: {identity.root}")
        viewer = observed.user_identity(project).name
        return CommsNavigation(CommsViewKey(identity.root, identity.key), viewer,
                               identity.key.threads_needed(observed, viewer))

    def original_threads(self, sessions):
        return tuple((self.key.root, participant) for participant in self.participants)

    def original_channels(self):
        return self.key.conversation.channels_needed(self.key.root)

    @property
    def address(self) -> object:
        return self.key.conversation.view_identity(self.key)

    def unobserved_tab(self) -> OpenTab:
        return NamedTab(self.identity, self.key.conversation.initial_label)

    def tab(self, sessions: SessionNavigator, observed: Observing) -> OpenTab:
        return self.project_value(observed.references_for(self.key.root), observed)

    @handles(ReferenceContext)
    def preparing_tab(self, references, observed) -> OpenTab:
        return self.unobserved_tab()

    @handles(CurrentDisplayReferences)
    def referenced_tab(self, references, observed) -> OpenTab:
        conversation = self.key.conversation
        return ConversationTab(
            self.identity,
            conversation.label(references),
            conversation,
            observed.sidebar,
        )

    async def ready(self, sessions: SessionNavigator) -> None:
        await sessions.app.workspace_sessions.require(self.mode).wait_content_ready()
