"""Shared conversation identity and Core-read behavior.

ConversationKind owns stable destinations, page reads, sidebar interest,
member resolution and status. Native methods (compose_activity, prompt,
toggle) stay on native conversation members — they are NOT on this base.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from agent_comms.messaging.channel_targets import NamedTarget
from agent_comms.messaging.display_references import ThreadNames
from agent_comms.messaging.message_page import MessagePage, PageBounds
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.projects.checkouts import Checkout
from agent_comms.transport.request import CoreAccess
from agent_comms.transport.tools.sidebar import CommsConversationPageTool
from agent_comms.ui_model.sidebar import SidebarModel, SidebarObservation

from toad.client.submission import MessageDestination
from toad.conversation_capabilities import ConversationActivity, ConversationSource
from toad.referenced_core import ReferencedCore
from toad.session_tracker import CommsViewKey
from toad.status_thread import NoStatusThread, StatusThread


class SharedConversationKind(MessageDestination, DeclaredFamily, affix="Conversation"):
    """Cross-framework conversation behavior — identity, routing, Core reads.

    Native frameworks add compose_activity, prompt and toggle methods
    on their own subclasses. This class has NO Textual or Qt imports.
    """

    @property
    @abstractmethod
    def initial_label(self) -> str: ...

    @property
    @abstractmethod
    def input_scope(self) -> str: ...

    @abstractmethod
    def destination(self, references: ThreadNames) -> NamedTarget: ...

    @abstractmethod
    def retained_target(self) -> NamedTarget: ...

    def sidebar_threads(self):
        return ()

    def threads_needed(self, source, me: str):
        return ()

    def channels_needed(self, root: str):
        return ()

    @classmethod
    def view_identity(cls, key: CommsViewKey):
        return key

    def page(self, source: ConversationSource, bounds: PageBounds) -> MessagePage:
        return source.core.call(CommsConversationPageTool(
            conversation=self.retained_target(), project=source.project, bounds=bounds))

    @classmethod
    @abstractmethod
    def resolve(cls, source, me: str, name: str): ...

    def label(self, references: ThreadNames) -> str:
        return self.destination(references).name

    def status_thread(self, root: Path, access) -> StatusThread:
        return NoStatusThread()

    def historical_sessions(self, create_view: partial, references: ThreadNames):
        return create_view()

    def unread(self, observation: SidebarObservation):
        return observation.channel_unread(self.retained_target().name)

    def send_target(self) -> NamedTarget:
        return self.retained_target()

    def read_only(self, core: CoreAccess) -> bool:
        return False

    @classmethod
    @abstractmethod
    async def update_mentions(cls, view: ConversationActivity, source) -> None: ...

    @abstractmethod
    async def status_text(self, source, *, read_only: bool) -> str: ...

    def activity_members(self, model: SidebarModel):
        return (self.destination(model.observation.thread_names()).name,)

    def active_members(self, model: SidebarModel):
        return tuple(
            model.threads.rows[name] for name in self.activity_members(model) if model.threads.rows[name].active
        )

    @classmethod
    def seen_page(cls, seen):
        if not seen:
            return None
        page = seen[0].evidence
        marked = tuple(fragment for fragment in seen if fragment.evidence is page)
        return page.select(fragment.message.seq for fragment in marked), marked


@dataclass(frozen=True)
class ResolvedConversation:
    viewer: str
    conversation: SharedConversationKind
