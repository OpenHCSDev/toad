"""Conversation operations supplied by their actual source, screen and chat owners."""
from abc import abstractmethod

from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_identity import ThreadIncarnation
from textual.abstract_hooks import AbstractHooksMeta
from textual.app import ComposeResult

from toad.referenced_core import ReferencedCore


class ConversationSource(ReferencedCore):
    """A referenced Core read in one checkout."""

    project: Checkout


class ConversationNavigation(metaclass=AbstractHooksMeta):
    """The screen owns the UI effects a conversation selects."""

    @abstractmethod
    async def show_feed(self) -> None: ...

    @abstractmethod
    async def return_to_view(self) -> None: ...

    @abstractmethod
    async def show_direct_messages(self) -> None: ...


class ConversationActivity(metaclass=AbstractHooksMeta):
    """The chat owns its widgets and asynchronous mention publication."""

    @abstractmethod
    def compose_channel_activity(self) -> ComposeResult: ...

    @abstractmethod
    def compose_peer_activity(self, peer: ThreadIncarnation) -> ComposeResult: ...

    @abstractmethod
    async def update_channel_mentions(self, source: ReferencedCore) -> None: ...
