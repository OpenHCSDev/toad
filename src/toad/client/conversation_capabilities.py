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

    def channel_prompt(self, placeholder: str):
        raise NotImplementedError

    def message_prompt(self):
        raise NotImplementedError

    def channel_prompt_kind(self) -> type:
        raise NotImplementedError

    def message_prompt_kind(self) -> type:
        raise NotImplementedError

    async def update_channel_mentions(self, source: ReferencedCore) -> None:
        """Read who can be mentioned in this conversation and tell the composer. One sequence
        for both frontends: the candidates are prepared off the UI thread, for a root this
        view observes, and are told only to a view still showing the conversation and source
        they were read for. Qt's view ran the read with neither check, so a view that had
        moved on while it ran was told the names of where it had been (2026-11-22: NRA's
        sibling-override-step finding; the read can take seconds on a busy bus)."""
        history = self.message_history
        shown = history.source_snapshot()
        conversation = self.conversation
        access = self.app.coordination_access
        answer = await access.current_sidebar()
        if not access.observation.observes(source.root):
            raise ValueError("Channel mentions belong to another Core root")
        mentions = await self.app.preparation.run_thread(conversation.mention_candidates, answer)
        if not await history.source_is_current(shown) or self.conversation != conversation:
            return
        self.show_mention_candidates(mentions)

    def show_mention_candidates(self, mentions) -> None:
        """Hand the composer, if the view has one, the names it completes after an @."""
        raise NotImplementedError
