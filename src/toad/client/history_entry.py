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
from agent_comms.registry.thread_identity import ThreadIncarnation
from metaclass_registry.mro_dispatch import handles

from toad.client.connection import Observing
from toad.client.conversation import CommsViewKey
from toad.client.session_entry import SharedSessionEntry
from toad.client.session_tracker import ConversationTab, NamedTab, OpenTab
from toad.client.tab_identity import TabIdentity
from toad.core.projection import MroProjection


class SharedHistorySessionEntry[Navigator](
    SharedSessionEntry[Navigator], MroProjection[OpenTab], declared_name=None
):
    def __init__(
        self,
        identity: TabIdentity,
        key: CommsViewKey,
        project: Checkout,
        viewer: str,
        participants: tuple[ThreadIncarnation, ...],
    ) -> None:
        """The owner's tab for one conversation; no session owns it, so none closes or returns it."""
        super().__init__(identity)
        self.key, self.project, self.viewer, self.participants = key, project, viewer, participants

    def original_threads(self, sessions):
        return tuple((self.key.root, participant) for participant in self.participants)

    def original_channels(self):
        return self.key.conversation.channels_needed(self.key.root)

    @property
    def address(self) -> object:
        return self.key.conversation.view_identity(self.key)

    def unobserved_tab(self) -> OpenTab:
        return NamedTab(self.identity, self.key.conversation.initial_label)

    def tab(self, sessions: Navigator, observed: Observing) -> OpenTab:
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
