"""Source-fenced saved transcript publication; checkpoint policy stays declared."""
from __future__ import annotations

import weakref
import asyncio
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from functools import partial
from typing import TYPE_CHECKING

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from textual.worker import Worker, WorkerCancelled
from textual.await_complete import AwaitComplete

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

    async def publish(self) -> bool:
        """Join original UI application before capturing source-transfer custody.

        Ordered ACP ingress can already report a settled source while its
        original body messages are still queued on the Conversation. Only that
        native pump can certify that those effects have applied. Reads and
        preparation start after the join, with the same actor and generation.
        """
        if not self.current():
            return True
        view = self.owner.view
        pump = view.task
        if asyncio.current_task() is pump:
            # A snapshot notification itself runs on this pump. Its existing
            # source worker must perform the join; waiting here blocks the very
            # messages whose resource custody the source needs to capture.
            self.owner.source_requests.submit(self)
            return True
        from agent_comms.coordination_errors import CoordinationReadUnavailable, StaleRevision
        from agent_comms.errors import UnregisteredThreadError

        try:
            if await self.capture_application():
                return await self.publish_applied()
        except CoordinationReadUnavailable:
            # No source snapshot was acquired. Keep the original operation,
            # mounted history and admission unchanged until a new observation
            # or the existing preparation completion resumes source work.
            if self.current():
                self.owner.source_requests.defer(self)
                return False
        except (StaleRevision, UnregisteredThreadError):
            # The original backend read lost its source. Every publication
            # declines it here; only a new observation can admit another read.
            return True
        except (OSError, ValueError) as error:
            self.report_failure(error)
        return True

    def report_failure(self, error: Exception) -> None:
        """Keep genuine read/preparation failures distinct from retirement."""
        raise error

    async def capture_application(self) -> bool:
        """Capture the original applied cohort once its source cut is known."""
        if not await self.application_current():
            return False
        self.captured = self.owner.view.turns.owner.captured_snapshot(tuple(self.contents.children))
        return True

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
    async def publish_applied(self) -> bool: ...


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

    async def publish_applied(self) -> bool:
        # The original supplied page is already known at the inherited join.
        await self.publish_page()
        return True

    async def publish_page(self) -> None:
        """Admit this operation's known cut and original applied resource cohort."""
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
        async with AsyncExitStack() as retirement:
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
                        retirement.push_async_callback(
                            self.owner.retire_presentations(self.contents, view.output, retired)
                        )
                    finally:
                        # A provisional mount owns no source coverage. Its cleanup
                        # must finish before native frame admission is released.
                        # Accepted source survives cancellation while old rows retire.
                        if not accepted and history.is_attached:
                            retirement.push_async_callback(
                                self.owner.retire_presentations(self.contents, view.output, [history])
                            )
        self.owner.painted(self.page.after, reader_revision=self.scroll_revision)


class HandlingPublication(TranscriptPublication):
    """Render original recipient outcomes on existing original source bodies."""

    async def publish_applied(self) -> bool:
        from toad.widgets.wire_message_handling import WireMessageHandling

        if self.agent is None:
            return True
        bodies = WireMessageHandling.within(self.contents)
        references = WireMessageHandling.references_in(bodies)
        if not references:
            return True
        results = await self.agent.get_message_notifications(references)
        if self.current():
            for body in bodies:
                if body.is_attached:
                    body.show_notifications(results)
        return True


class CanonicalSourcePublication(TranscriptPublication):
    """An observed source change refreshes source pages, never appends a notice."""

    async def read_page(self) -> TranscriptPage:
        return await self.agent.get_transcript_page()

    async def publish_applied(self) -> bool:
        if self.agent is None or not self.agent.transcript_ready:
            return True
        page = await self.read_page()
        # The known native cut and its applied original resources meet here.
        # An expired application cannot publish this read; it is not a stale
        # backend revision and must not escape as a failed Textual worker.
        if not await self.capture_application():
            return True
        bound = self.source_bound(page.after)
        if bound != page.after:
            self.owner.dirty = self.owner.checkpoint_required = True
            page = await self.agent.get_transcript_page(through=bound)
            # Preserve this cut's original cohort across the bounded read.
            if not await self.application_current():
                return True
        return await self.publish_source_page(page)

    async def publish_source_page(self, page: TranscriptPage) -> bool:
        # Supplied snapshots capture their own application boundary. This
        # original read already joined and retains that exact resource cohort.
        snapshot = SnapshotPublication(self.owner, self.owner.view,
                                       self.window, self.contents, page)
        snapshot.captured = self.captured
        await snapshot.publish_page()
        return await self.owner.publish(HandlingPublication)


class ObservedSourcePublication(CanonicalSourcePublication):
    def __init__(self, owner, view, window, contents, presentation):
        super().__init__(owner, view, window, contents)
        self.presentation = presentation

    async def read_page(self) -> TranscriptPage:
        identity = self.presentation.read_identity
        return await self.agent.get_transcript_page(read_identity=identity)

    async def publish_applied(self) -> bool:
        if self.agent is None:
            return True
        await self.agent.observe_thread_presentation(self.presentation)
        if self.current():
            return await super().publish_applied()
        return True


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
        self.resume()

    def defer(self, publication: TranscriptPublication) -> None:
        """Retain a busy original read without replacing newer source work."""
        if self.pending.empty():
            self.pending.put_nowait(publication)
        view = self.owner.view
        view.retire_core_observations(view.app.coordination_access.events)
        view.observe_core_callback(view.app.coordination_access.events, self.resume)

    def resume(self, _event=None) -> bool:
        """Resume retained work only at an existing source/preparation signal."""
        if self.pending.empty():
            return False
        if self.worker is None or self.worker.is_finished:
            view = self.owner.view
            view.retire_core_observations(view.app.coordination_access.events)
            self.worker = view.run_worker(self.publish, group="transcript-source")
        return True

    async def publish(self) -> None:
        while not self.pending.empty():
            publication = self.pending.get_nowait()
            if not await publication.publish():
                return

    def cancel(self) -> Worker[None] | None:
        view = self.owner.view
        if view is not None:
            view.retire_core_observations(view.app.coordination_access.events)
        while not self.pending.empty():
            self.pending.get_nowait()
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.cancel()
        return worker


class CheckpointPublication(CanonicalSourcePublication):
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

    async def publish_applied(self) -> bool:
        if self.admitted():
            return await super().publish_applied()
        return True

    def report_failure(self, error: Exception) -> None:
        if self.current():
            self.owner.view.notify(str(error), title="Committed history", severity="error")

    async def publish_source_page(self, page: TranscriptPage) -> bool:
        from toad.widgets.committed_presentation import (
            CommitEvidence,
            CommittedHistory,
            retirement_candidates,
        )
        from toad.widgets.transcript_history import TranscriptHistory

        view = self.owner.view
        if view is None:
            return True
        window, contents = self.window, self.contents
        if not self.admitted():
            return True
        plan = self.plan
        # A page cannot replace live blocks posted while its read or fragment
        # preparation is in flight unless it explicitly contains their identity.
        original_children = tuple(contents.children)
        history = next(
            (child for child in original_children if isinstance(child, CommittedHistory)),
            None,
        )
        is_current = partial(self.source_current, page.after)
        if not page.events or not is_current():
            return True
        prepared = await plan.prepare(view, history, page, self.captured, is_current)
        if prepared is None or not is_current():
            return True
        evidence = CommitEvidence(
            self.captured, prepared.sequences, prepared.history,
            frozenset(native_id for event in page.events for native_id in event.native_inputs),
        )
        async with AsyncExitStack() as retirement:
            async with window.history_lock:
                retired = retirement_candidates(contents.children, evidence)
                if (
                    not is_current()
                    or history is not next(iter(self.owner.histories), None)
                    or not plan.ready(prepared.history)
                    or not plan.permits(view, retired)
                ):
                    return True
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
                            return True
                        # Identity-backed arrivals during a mount may now be covered;
                        # ordinary late arrivals remain outside the captured cohort.
                        retired = retirement_candidates(contents.children, evidence)
                        if not plan.permits(view, retired):
                            return True
                        plan.commit(prepared, page.after)
                        if replacement is not None:
                            replacement.publish_committed()
                        # Once retiring live widgets begins, the accepted source must
                        # survive cancellation so their saved content stays reachable.
                        accepted = True
                        retirement.push_async_callback(
                            self.owner.retire_presentations(contents, view.output, retired)
                        )
                    finally:
                        if (
                            not accepted
                            and replacement is not None
                            and replacement.is_attached
                        ):
                            retirement.push_async_callback(
                                self.owner.retire_presentations(contents, view.output, [replacement])
                            )
        if not window.is_attached or not contents.is_attached:
            return True
        if self.native_current():
            self.owner.dirty = False
            self.owner.checkpoint_required = False
        plan.finish(view, page.after)
        return True



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
        source = view.query_ancestor(SessionView)
        publication = self.capture(CanonicalSourcePublication)
        if history is not None:
            await self.reveal_retained(history)
        view.refresh_native_projection()

        def refresh_after_paint() -> None:
            if (publication is not None and publication.agent is agent
                    and view.app.workspace_sessions.owns(source)):
                view.run_worker(publication.publish(),
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

    async def publish(self, kind: type[TranscriptPublication], *args) -> bool:
        publication = self.capture(kind, *args)
        if publication is not None and publication.current():
            return await publication.publish()
        return True

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
        if self.source_requests.resume():
            return
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
            # Exclusive replacement/cancel can detach the current handle while
            # an older accepted publication still joins its retirement. The
            # framework manager owns those actual tasks until completion.
            workers.extend(view.workers.cancel_group(view, "transcript-window"))
            workers.extend(view.workers.cancel_group(view, "transcript-source"))
            workers.extend(view.workers.cancel_group(view, "transcript-handling"))
            workers.extend(view.workers.cancel_group(view, "retained-native-refresh"))
        for worker in workers:
            if worker is None:
                continue
            worker.cancel()
            try:
                await worker.wait()
            except WorkerCancelled:
                pass

    def covered(self, message) -> AwaitComplete:
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
            return AwaitComplete.nothing()
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
            retirement = self.retire_presentations(contents, view.output,
                [child for child in candidates if child not in protected])

            async def complete() -> None:
                await retirement
                # The accepted frontier also invalidates its existing status view.
                # A retained resume can reject an identical snapshot without any
                # widget replacement; it still publishes canonical coverage here.
                view.query_one(SessionDetails)._refresh_summary()
                from toad.widgets.observed_thread_activity import ObservedThreadActivity
                observed = view.query_one_optional(ObservedThreadActivity)
                if observed is not None and observed.presentation is not None:
                    view.run_worker(partial(self.publish, HandlingPublication),
                                    group="transcript-handling", exclusive=True)

            return AwaitComplete(complete())
        return AwaitComplete.nothing()

    def retire_presentations(self, contents, output, candidates) -> AwaitComplete:
        """Withdraw covered native paint now; join teardown outside source locks.

        CommitEvidence has already selected these exact resources. Their native
        display lifetime ends synchronously, so accepted saved rows cannot paint
        alongside them while an original stream finishes its paged publication.
        The independent teardown owns cancellation custody; source transactions
        register this receipt outside their mutation locks.
        """
        if not candidates:
            return AwaitComplete.nothing()
        for candidate in candidates:
            candidate.display = False
        retirement = asyncio.create_task(
            self._retire_presentations(contents, output, candidates),
            name="accepted source retirement",
        )
        return AwaitComplete(self._join_retirement(retirement))

    async def _join_retirement(self, retirement) -> None:
        caller = asyncio.current_task()
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
