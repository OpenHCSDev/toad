"""A channel or direct conversation's history as every frontend reads it: which painted messages
wait to be marked read, and the acknowledgement that marks them."""
from abc import abstractmethod

from agent_comms.coordination.errors import ReadAgain
from agent_comms.messaging.historical_views import UnobservedConversation
from agent_comms.messaging.message_page import MessagePage

from toad.client.fragments import EvidencedFragment, FragmentKey
from toad.client.history_preparation import HistorySourceSnapshot
from toad.client.history_reads import NothingToRead, PaintedRead, ReadMarking
from toad.client.prepared_pages import ReplaceablePageSource


class ReadMarkedHistory(ReadMarking):
    """A history whose painted messages are acknowledged: the one map of painted evidence
    waiting for Core, and the acknowledgement that retires it. A mixin beside the native
    history, so its hooks are declared without ABC's metaclass."""

    page_source: ReplaceablePageSource

    def __init__(self, *args, **kwargs) -> None:
        self._painted_reads: dict[FragmentKey, EvidencedFragment] = {}
        super().__init__(*args, **kwargs)

    @property
    @abstractmethod
    def undrawn(self) -> bool: ...

    @abstractmethod
    async def source_is_current(self, snapshot: HistorySourceSnapshot) -> bool: ...

    @abstractmethod
    def mark_visible_after_paint(self) -> None:
        """Try marking read again once the frontend has painted its next frame."""

    @abstractmethod
    def withdraw_view(self) -> None:
        """The route no longer reads this conversation: stop showing it."""

    @abstractmethod
    async def refresh_source(self) -> None:
        """Read the conversation again, as the view reads it now."""

    def retain_painted(self, fragment: EvidencedFragment) -> None:
        """Keep actual painted evidence until its original page is acknowledged."""
        if fragment.evidence is not None and self._painted_reads.get(fragment.key) is not fragment:
            self._painted_reads[fragment.key] = fragment
            self.mark_visible_after_paint()

    def retire_painted(self, fragments: tuple[EvidencedFragment, ...], proof: MessagePage) -> None:
        """Release only these receipts, never a newer paint of the same message."""
        for fragment in fragments:
            if fragment.evidence is proof:
                fragment.evidence = None
                if self._painted_reads.get(fragment.key) is fragment:
                    del self._painted_reads[fragment.key]

    def read_fragments(self) -> tuple[EvidencedFragment, ...]:
        if not self.is_attached or not self.can_draw_on_screen:
            return ()
        return tuple(self._painted_reads.values())

    def read_visible(self) -> PaintedRead:
        if not self.is_attached:
            return NothingToRead()
        if not any(fragment.evidence is not None for fragment in self.read_fragments()):
            return NothingToRead()
        return self.page_source.painted_read(self)

    async def _mark_read(self, snapshot: HistorySourceSnapshot) -> None:
        if not await self.source_is_current(snapshot):
            if snapshot.current(self):
                self.withdraw_view()
            elif self.is_attached:
                self.mark_visible_after_paint()
            return
        seen = tuple(fragment for fragment in self.read_fragments() if fragment.evidence is not None)
        if (selected := self.page_source.seen_page(self, seen)) is not None:
            await self._mark_page(*selected, snapshot)

    async def _mark_page(
        self, page: MessagePage, marked: tuple[EvidencedFragment, ...], snapshot: HistorySourceSnapshot
    ) -> None:
        source = self.page_source
        proof = marked[0].evidence
        try:
            await source.mark_page(page)
            self.retire_painted(marked, proof)
        except ReadAgain:
            # Every queued fragment carrying that same refused proof must
            # release it before reloading can paint a replacement. Keep
            # unrelated proofs and any newer paint already queued meanwhile.
            refused = tuple(fragment for fragment in self._painted_reads.values()
                            if fragment.evidence is proof)
            self.retire_painted((*marked, *refused), proof)
            # The viewer, peer, channel scope or bus changed after the page
            # was read: draw the conversation as it is read now.
            if snapshot.current(self):
                await self.reload_notification_source()
        finally:
            if self.is_attached:
                self.mark_visible_after_paint()

    async def reload_notification_source(self) -> None:
        """Forget what was observed, so the next refresh reads the page and its cut afresh."""
        self.page_source.revision = UnobservedConversation()
        await self.refresh_source()
