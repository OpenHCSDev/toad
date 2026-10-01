"""Source-fenced saved transcript publication; checkpoint policy stays declared."""
from __future__ import annotations

import weakref
import asyncio
from abc import ABC, abstractmethod
from functools import partial
from typing import TYPE_CHECKING

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from textual.worker import Worker, WorkerCancelled

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation, Window, Contents
    from toad.widgets.history_anchor import ReaderPosition
    from toad.widgets.transcript_history import TranscriptHistory


class TranscriptPublication(ABC):
    """A single read/publication's source, resource and generation custody."""

    def __init__(self, owner: TranscriptPresentation, view: Conversation,
                 window: Window, contents: Contents) -> None:
        self.owner = owner
        self.generation = owner.generation
        self.agent = view.agent
        self.window, self.contents = window, contents
        self.captured = view.turns.owner.captured_snapshot(tuple(contents.children))

    def native_current(self) -> bool:
        """Only anonymous native output requires settled resource custody."""
        from toad.widgets.committed_presentation import CommitParticipant

        return self.current() and all(
            widget.commit_claim.admits_native(widget, self.captured)
            for widget in self.contents.children if isinstance(widget, CommitParticipant)
        )

    def source_bound(self, cursor: TranscriptCursor) -> TranscriptCursor:
        """Wire assignment can advance without transferring anonymous native output.

        The mounted canonical history retains the native/outcome prefix. The
        current certified source supplies its original assigned-wire frontier.
        This is a bounded read of that source, not another presentation store.
        """
        if self.native_current():
            return cursor
        prefixes = tuple(bound for history in self.owner.histories
                         if history in self.captured and history.state.reports_coverage
                         for bound in (history.committed_cursor,)
                         if bound.receipts_within(cursor))
        prefix = max((bound for bound in prefixes if bound.session_file == cursor.session_file),
                     key=lambda bound: bound.offset,
                     default=next(iter(prefixes), TranscriptCursor(cursor.session_file, 0)))
        return TranscriptCursor(prefix.session_file, prefix.offset,
                                cursor.receipts, prefix.outcomes)

    def source_current(self, cursor: TranscriptCursor) -> bool:
        return self.current() and self.source_bound(cursor) == cursor

    async def read_source_page(self) -> TranscriptPage:
        page = await self.agent.get_transcript_page()
        return await self.read_bound(page)

    async def read_bound(self, page: TranscriptPage) -> TranscriptPage:
        bound = self.source_bound(page.after)
        if bound != page.after:
            self.owner.dirty = self.owner.checkpoint_required = True
            page = await self.agent.get_transcript_page(through=bound)
        return page

    def current(self) -> bool:
        from toad.widgets.conversation import Window, Contents
        view = self.owner.view
        if view is None or not view.is_attached or view._closing:
            return False
        if self.generation != self.owner.generation or view.agent is not self.agent:
            return False
        return (self.window.is_attached and self.contents.is_attached
                and view.query_one_optional(Window) is self.window
                and view.query_one_optional(Contents) is self.contents)

    async def publish(self) -> None:
        """Join original UI application before capturing source-transfer custody.

        Ordered ACP ingress can already report a settled source while its
        original body messages are still queued on the Conversation. Only that
        native pump can certify that those effects have applied. Reads and
        preparation start after the join, with the same actor and generation.
        """
        if not self.current():
            return
        view = self.owner.view
        pump = view.task
        if asyncio.current_task() is pump:
            # A snapshot notification itself runs on this pump. Its existing
            # source worker must perform the join; waiting here blocks the very
            # messages whose resource custody the source needs to capture.
            self.owner.source_requests.submit(self)
            return
        if await self.application_current():
            self.captured = view.turns.owner.captured_snapshot(tuple(self.contents.children))
            await self.publish_applied()

    async def application_current(self) -> bool:
        """The original native pump attests applied effects at this source cut."""
        if not self.current():
            return False
        view = self.owner.view
        pump = view.task
        applied = asyncio.get_running_loop().create_future()

        def complete() -> None:
            if not applied.done():
                applied.set_result(None)

        if not view.call_later(complete):
            return False
        try:
            await asyncio.wait((applied, pump), return_when=asyncio.FIRST_COMPLETED)
            return applied.done() and self.current()
        finally:
            applied.cancel()

    @abstractmethod
    async def publish_applied(self) -> None: ...


class SnapshotPublication(TranscriptPublication):
    def __init__(self, owner, view, window, contents, page: TranscriptPage):
        super().__init__(owner, view, window, contents)
        self.page = page
        self.scroll_revision = window.scroll_revision

    def admitted(self) -> bool:
        """The mounted source frontier owns admission, under its window lock."""
        frontiers = (history.committed_cursor for history in self.owner.histories
                     if history.is_attached and history.state.reports_coverage)
        frontier = max((cursor for cursor in frontiers
                        if cursor.session_file == self.page.after.session_file),
                       key=lambda cursor: (cursor.offset, cursor.wire_seq), default=None)
        if frontier is None:
            return True
        if not frontier.contains(self.page.after):
            self.owner.require_checkpoint()
        return False

    async def publish_applied(self) -> None:
        from toad.render_tasks import TranscriptRenderTask
        from toad.work_preparation import RenderPreparation
        from toad.widgets.transcript_history import TranscriptHistory
        from toad.widgets.committed_presentation import (
            CommitEvidence, retirement_candidates,
        )
        async with self.window.history_lock:
            if not self.current():
                return
            if not self.source_current(self.page.after):
                self.owner.require_checkpoint()
                return
            for history in self.owner.histories:
                history.state.validate_snapshot(history, self.page)
            if not self.admitted():
                return
        fragments = await self.owner.view.app.preparation.submit(
            RenderPreparation(TranscriptRenderTask(self.page.events))
        )
        if not self.current() or self.agent is None:
            return
        view = self.owner.view
        async with self.window.history_lock:
            # Preparation may yield to another accepted source publication.
            # Recheck the original operation against those actual resources;
            # a pre-render absence check cannot authorize a second full page.
            if not self.current() or not self.admitted():
                return
            if not self.source_current(self.page.after):
                self.owner.require_checkpoint()
                return
            history = TranscriptHistory(self.page, self.agent.get_transcript_page,
                                        fragments=fragments, committed=False)
            self.owner.prepare_reader(history)
            async with self.window.preserve_history(None):
                accepted = False
                try:
                    await self.contents.mount(history)
                    if not self.source_current(self.page.after):
                        if self.current():
                            self.owner.require_checkpoint()
                        return
                    # This accepted full source replaces exactly the old
                    # history resources captured before its mount. Original
                    # live inputs still need native identity evidence.
                    evidence = CommitEvidence(
                        self.captured, retained_history=history,
                        native_inputs=frozenset(native_id for event in self.page.events
                                                for native_id in event.native_inputs),
                    )
                    history.publish_committed()
                    accepted = True
                    retired = retirement_candidates(self.contents.children, evidence)
                    await self.owner.retire_presentations(self.contents, view.output, retired)
                finally:
                    # A provisional mount owns no source coverage. Its cleanup
                    # must finish before native frame admission is released.
                    # Accepted source survives cancellation while old rows retire.
                    if not accepted and history.is_attached:
                        await history.remove()
        self.owner.painted(self.page.after, reader_revision=self.scroll_revision)


class HandlingPublication(TranscriptPublication):
    """Render original recipient outcomes on existing original source bodies."""

    async def publish_applied(self) -> None:
        from toad.widgets.wire_message_handling import WireMessageHandling

        if self.agent is None:
            return
        bodies = tuple(body for body in self.contents.walk_children()
                       if isinstance(body, WireMessageHandling) and body.handling_references)
        references = tuple(dict.fromkeys(reference for body in bodies
                                         for reference in body.handling_references))
        if not references:
            return
        results = await self.agent.get_message_notifications(references)
        if self.current():
            for body in bodies:
                if body.is_attached:
                    body.show_notifications(results)


class CanonicalSourcePublication(TranscriptPublication):
    """An observed source change refreshes source pages, never appends a notice."""

    async def read_page(self) -> TranscriptPage:
        return await self.read_source_page()

    async def publish_applied(self) -> None:
        if self.agent is None or not self.agent.transcript_ready:
            return
        page = await self.read_page()
        if self.current():
            await self.owner.snapshot(page)
            await self.owner.publish(HandlingPublication)


class ObservedSourcePublication(CanonicalSourcePublication):
    def __init__(self, owner, view, window, contents, presentation):
        super().__init__(owner, view, window, contents)
        self.presentation = presentation

    async def read_page(self) -> TranscriptPage:
        identity = self.presentation.read_identity
        bound = self.source_bound(identity.page_bound)
        if bound != identity.page_bound:
            self.owner.dirty = self.owner.checkpoint_required = True
            return await self.agent.get_transcript_page(through=bound)
        return await self.agent.get_transcript_page(read_identity=identity)

    async def publish_applied(self) -> None:
        if self.agent is None:
            return
        await self.agent.observe_thread_presentation(self.presentation)
        if self.current():
            await super().publish_applied()


class SourcePublicationRequests:
    """One running read and one coalesced original request, never model state."""

    def __init__(self, owner: TranscriptPresentation):
        self.owner = owner
        self.pending: asyncio.Queue[TranscriptPublication] = asyncio.Queue(maxsize=1)
        self.worker: Worker[None] | None = None

    def request(self, kind: type[TranscriptPublication], *args: object) -> None:
        publication = self.owner.capture(kind, *args)
        if publication is None:
            return
        self.submit(publication)

    def submit(self, publication: TranscriptPublication) -> None:
        """Keep the original operation when its caller is the native UI pump."""
        if self.pending.full():
            self.pending.get_nowait()
        self.pending.put_nowait(publication)
        if self.worker is None or self.worker.is_finished:
            self.worker = self.owner.view.run_worker(self.publish, group="transcript-source")

    async def publish(self) -> None:
        from agent_comms.coordination_errors import StaleRevision

        while not self.pending.empty():
            publication = self.pending.get_nowait()
            try:
                if publication.current():
                    await publication.publish()
            except StaleRevision:
                # A changed original source declines this request. A subsequent
                # observation owns the next read; do not spin on page capture.
                continue

    def cancel(self) -> Worker[None] | None:
        while not self.pending.empty():
            self.pending.get_nowait()
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.cancel()
        return worker


class CheckpointPublication(TranscriptPublication):
    def __init__(self, owner, view, window, contents):
        from toad.widgets.committed_presentation import checkpoint_plan
        super().__init__(owner, view, window, contents)
        self.plan = checkpoint_plan(window)

    def current(self) -> bool:
        view = self.owner.view
        return (super().current() and not view._pruning
                and self.plan.current(self.window))

    def admitted(self) -> bool:
        from toad.acp.agent import Agent
        from toad.widgets.committed_presentation import (
            CheckpointBarrier, CommitParticipant, CommittedHistory,
        )

        view = self.owner.view
        if not self.current() or not self.owner.dirty:
            return False
        if not isinstance(self.agent, Agent) or not view.agent_ready or not self.agent.transcript_ready:
            return False
        if any(isinstance(node, CheckpointBarrier) for node in self.contents.walk_children()):
            return False
        if not self.owner.checkpoint_required and len(self.contents.children) < view.MAX_LIVE_BLOCKS:
            return False
        history = next((child for child in self.contents.children
                        if isinstance(child, CommittedHistory)), None)
        potential = tuple(child for child in self.contents.children
                          if child is not history and isinstance(child, CommitParticipant))
        return self.plan.ready(history) and self.plan.permits(view, potential)

    async def publish_applied(self) -> None:
        from agent_comms.errors import UnregisteredThreadError
        from agent_comms.coordination_errors import StaleRevision

        from toad.widgets.committed_presentation import (
            CommitEvidence,
            CommittedHistory,
            retirement_candidates,
        )
        from toad.widgets.transcript_history import TranscriptHistory

        view = self.owner.view
        if view is None:
            return
        window, contents = self.window, self.contents
        if not self.admitted():
            return
        plan = self.plan
        # A page cannot replace live blocks posted while its read or fragment
        # preparation is in flight unless it explicitly contains their identity.
        before_read = tuple(contents.children)
        history = next(
            (child for child in before_read if isinstance(child, CommittedHistory)),
            None,
        )
        try:
            page = await self.read_source_page()
            # Reading can yield to later original notifications. Their UI
            # effects must apply before this page's native-claim admission,
            # including plans that admit pages during preparation. Keep the
            # original captured cohort: late anonymous output cannot be
            # transferred by an earlier operation's source evidence.
            if not await self.application_current():
                return
            is_current = partial(self.source_current, page.after)
            if not page.events or not is_current():
                return
            prepared = await plan.prepare(view, history, page, self.captured, is_current)
        except (UnregisteredThreadError, StaleRevision):
            # Deletion can retire the model before the attachment's final
            # transcript notification has drained. Its view is closing too.
            return
        except (OSError, ValueError) as error:
            if self.current():
                view.notify(str(error), title="Committed history", severity="error")
            return
        if prepared is None or not is_current():
            return
        evidence = CommitEvidence(
            self.captured, prepared.sequences, prepared.history,
            frozenset(native_id for event in page.events for native_id in event.native_inputs),
        )
        async with window.history_lock:
            retired = retirement_candidates(contents.children, evidence)
            if (
                not is_current()
                or history is not next(iter(self.owner.histories), None)
                or not plan.ready(prepared.history)
                or not plan.permits(view, retired)
            ):
                return
            async with plan.publication(view, prepared):
                replacement = None
                accepted = False
                try:
                    if prepared.history is None:
                        replacement = TranscriptHistory(
                            page,
                            self.agent.get_transcript_page,
                            fragments=prepared.fragments,
                            committed=False,
                        )
                        await contents.mount(replacement, before=0)
                    if not is_current():
                        return
                    # Identity-backed arrivals during a mount may now be covered;
                    # ordinary late arrivals remain outside the captured cohort.
                    retired = retirement_candidates(contents.children, evidence)
                    if not plan.permits(view, retired):
                        return
                    plan.commit(prepared, page.after)
                    if replacement is not None:
                        replacement.publish_committed()
                    # Once retiring live widgets begins, the accepted source must
                    # survive cancellation so their saved content stays reachable.
                    accepted = True
                    await self.owner.retire_presentations(contents, view.output, retired)
                finally:
                    if (
                        not accepted
                        and replacement is not None
                        and replacement.is_attached
                    ):
                        await replacement.remove()
        if not window.is_attached or not contents.is_attached:
            return
        if self.native_current():
            self.owner.dirty = False
            self.owner.checkpoint_required = False
        plan.finish(view, page.after)



class TranscriptPresentation:
    """Owns projection frontier, invalidation and exclusive checkpoint lifetime."""

    def __init__(self, view: Conversation) -> None:
        self._view = weakref.ref(view)
        self.generation = 0
        self.dirty = False
        self.checkpoint_required = False
        self.displayed_cursor: TranscriptCursor | None = None
        self.worker: Worker[None] | None = None
        self.reader_position: ReaderPosition | None = None
        self.source_requests = SourcePublicationRequests(self)

    @property
    def view(self) -> Conversation | None:
        return self._view()

    @property
    def histories(self) -> tuple[TranscriptHistory, ...]:
        """Canonical saved sources are direct children of this transcript.

        A body may own pagers for its Markdown or filtered projection. Those
        rendering resources cannot certify this conversation's saved source.
        Native child custody, rather than another retained pointer, owns this
        relation through provisional mount, replacement, park and disposal.
        """
        from toad.widgets.transcript_history import TranscriptHistory

        view = self.view
        return tuple(view.contents.query_children(TranscriptHistory)) if view is not None else ()

    @property
    def reports_coverage(self) -> bool:
        return any(history.state.reports_coverage for history in self.histories)

    def invalidate(self) -> None:
        self.generation += 1

    def prepare_reader(self, history: TranscriptHistory) -> None:
        """Apply this source's owned reader intent before mounting its history."""
        position = self.reader_position
        if position is not None:
            position.prepare_history(history)

    async def restore_native(self, agent) -> None:
        """The live calling actor owns retained reveal and source validation."""
        from toad.screens.session_view import SessionView

        view = self.view
        history = next(iter(self.histories), None)
        if history is None:
            await view.present_retained_native_session()
            return
        source = view.query_ancestor(SessionView)
        await self.reveal_retained(history)
        view.refresh_native_projection()

        def refresh_after_paint() -> None:
            if view.app.workspace_sessions.owns(source) and view.agent is agent:
                view.run_worker(self.refresh_revealed(agent),
                                group="retained-native-refresh", exclusive=True)

        view.call_after_refresh(refresh_after_paint)

    async def reveal_retained(self, history: TranscriptHistory) -> None:
        """Display the mounted reader while its native source remains fenced."""
        from toad.widgets.conversation import ThreadLoading
        from toad.widgets.session_details import SessionDetails

        view = self.view
        if view is None or not view.is_attached:
            return
        self.displayed_cursor = history.committed_cursor
        self.reader_position = None
        if (loading := view.query_one_optional(ThreadLoading)) is not None:
            await loading.remove()
        view.remove_class("-initial-loading")
        view.query_one(SessionDetails)._refresh_summary()

    async def refresh_revealed(self, agent) -> None:
        """Validate the retained reader after its first completed display."""
        generation = self.generation
        page = await agent.get_transcript_page()
        view = self.view
        if (view is None or view.agent is not agent or generation != self.generation
                or not view.is_attached):
            return
        await self.snapshot(page)

    def capture(self, kind: type[TranscriptPublication], *args) -> TranscriptPublication | None:
        """Admit an operation with its original attachment and resource custody."""
        from toad.widgets.conversation import Window, Contents
        view = self.view
        if view is None or not view.is_attached:
            return None
        window, contents = view.query_one_optional(Window), view.query_one_optional(Contents)
        if window is None or contents is None:
            return None
        return kind(self, view, window, contents, *args)

    async def publish(self, kind: type[TranscriptPublication], *args) -> None:
        publication = self.capture(kind, *args)
        if publication is not None and publication.current():
            await publication.publish()

    async def snapshot(self, page: TranscriptPage) -> None:
        await self.publish(SnapshotPublication, page)

    def painted(self, cursor: TranscriptCursor, *, reader_revision: int | None = None) -> None:
        from toad.widgets.conversation import Window, Contents
        view = self.view
        if view is None:
            return
        generation, agent = self.generation, view.agent
        window, contents = view.query_one_optional(Window), view.query_one_optional(Contents)
        def record() -> None:
            if self.view is not view or not view.is_attached:
                return
            if self.generation != generation or view.agent is not agent:
                return
            if window is None or contents is None:
                return
            if window.is_attached and contents.is_attached:
                self.displayed_cursor = cursor
                if reader_revision is not None:
                    position, self.reader_position = self.reader_position, None
                    if position is not None and window.scroll_revision == reader_revision:
                        position.restore(window)
        view.call_after_refresh(record)

    def source_changed(self) -> None:
        self.source_requests.cancel()
        self.invalidate()
        self.dirty = self.checkpoint_required = False
        self.displayed_cursor = None
        self.reader_position = None
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.cancel()

    def changed(self, cursor: TranscriptCursor | None) -> None:
        self.invalidate()
        self.dirty = True
        if cursor is None:
            self.checkpoint_required = True
        else:
            self.painted(cursor)
        self.request()

    def require_checkpoint(self) -> None:
        self.invalidate()
        self.checkpoint_required = self.dirty = True
        self.request()

    def request(self) -> Worker[None] | None:
        if (view := self.view) is None or not view.is_attached:
            return None
        self.worker = view.run_worker(partial(self.publish, CheckpointPublication),
                                      group="transcript-window", exclusive=True)
        return self.worker

    def request_handling(self) -> None:
        view = self.view
        if view is not None and view.is_attached:
            view.run_worker(partial(self.publish, HandlingPublication),
                            group="transcript-handling", exclusive=True)

    def retry(self) -> None:
        if not self.dirty or self.worker is not None and not self.worker.is_finished:
            return
        publication = self.capture(CheckpointPublication)
        if publication is not None and publication.native_current() and publication.admitted():
            self.request()

    def source_work_finished(self, history) -> None:
        if history in self.histories:
            self.retry()

    async def close(self) -> None:
        await self.suspend()
        self._view = lambda: None

    async def suspend(self) -> None:
        """Revoke in-flight publications while retaining this source's mounted frontier."""
        self.invalidate()
        worker, self.worker = self.worker, None
        workers = [worker, self.source_requests.cancel()]
        if (view := self.view) is not None:
            workers.extend(view.workers.cancel_group(view, "transcript-handling"))
        for worker in workers:
            if worker is None:
                continue
            worker.cancel()
            try:
                await worker.wait()
            except WorkerCancelled:
                pass

    async def covered(self, message) -> None:
        from toad.widgets.conversation import Contents
        from toad.widgets.session_details import SessionDetails
        from toad.widgets.committed_presentation import (
            CommitEvidence,
            CommitParticipant,
            protected_blocks,
            retirement_candidates,
        )

        view = self.view
        if view is None:
            return
        contents = view.query_one_optional(Contents)
        if (
            contents is not None
            and message.history is not None
            and message.history.is_attached
            and message.history.parent is contents
        ):
            candidates = retirement_candidates(
                contents.children,
                CommitEvidence(
                    frozenset(),
                    frozenset(message.sequences) | message.history.covered_sequences(
                        frozenset(sequence for child in contents.children
                                  if isinstance(child, CommitParticipant)
                                  for sequence in child.commit_claim.required_sequences)),
                    message.history,
                    message.native_inputs,
                ),
            )
            protected = protected_blocks(view, candidates)
            await self.retire_presentations(contents, view.output,
                [child for child in candidates if child not in protected])
            # The accepted frontier also invalidates its existing status view.
            # A retained resume can reject an identical snapshot without any
            # widget replacement; it still publishes canonical coverage here.
            view.query_one(SessionDetails)._refresh_summary()
            from toad.widgets.observed_thread_activity import ObservedThreadActivity
            observed = view.query_one_optional(ObservedThreadActivity)
            if observed is not None and observed.presentation is not None:
                view.run_worker(partial(self.publish, HandlingPublication),
                                group="transcript-handling", exclusive=True)

    async def retire_presentations(self, contents, output, candidates) -> None:
        """Join accepted page or snapshot retirement before its frame fence opens."""
        if not candidates:
            return
        caller = asyncio.current_task()
        retirement = asyncio.create_task(
            self._retire_presentations(contents, output, candidates),
            name="accepted source retirement",
        )
        while not retirement.done():
            try:
                await asyncio.shield(retirement)
            except asyncio.CancelledError:
                if retirement.cancelled():
                    raise
        retirement.result()
        if caller.cancelling():
            raise asyncio.CancelledError

    async def _retire_presentations(self, contents, output, candidates) -> None:
        try:
            await output.retire_presentations(candidates)
        finally:
            await contents.remove_children(candidates)
