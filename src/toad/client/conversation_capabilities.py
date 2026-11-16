"""Conversation operations supplied by their actual source, screen and chat owners."""
from collections.abc import Iterator

from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_identity import ThreadIncarnation

from toad.client.referenced_core import ReferencedCore


class ConversationSource(ReferencedCore):
    """A referenced Core read in one checkout."""

    project: Checkout


class ConversationNavigation:
    """The screen owns the UI effects a conversation selects.

    Textual screens retain AbstractHooksMeta through their own widget bases.
    """

    async def show_feed(self) -> None:
        raise NotImplementedError

    async def return_to_view(self) -> None:
        raise NotImplementedError

    async def show_direct_messages(self) -> None:
        raise NotImplementedError


class ConversationActivity:
    """The chat owns its widgets and asynchronous mention publication.

    compose methods return native ComposeResult on each backend;
    the shared contract declares them as returning Iterator.
    """

    def compose_channel_activity(self) -> Iterator:
        raise NotImplementedError

    def compose_peer_activity(self, peer: ThreadIncarnation) -> Iterator:
        raise NotImplementedError

    async def update_channel_mentions(self, source: ReferencedCore) -> None:
        raise NotImplementedError
