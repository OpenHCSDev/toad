"""Source-fenced saved transcript publication; commit policy stays declared."""
from __future__ import annotations

import asyncio
from collections import deque
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack, asynccontextmanager
from toad.resource_release import AsyncResourceRelease, ResourceRelease
from functools import partial
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.transcripts import TranscriptCursor, TranscriptPage, TranscriptReadIdentity
from agent_comms.transcript_events import TranscriptCoverage
from agent_comms.acp_extension import TranscriptDraftUpdate, TranscriptSnapshotUpdate
from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.ui_model.observation import NotPublished, Published, TranscriptPublicationState
from agent_comms.coordination_errors import CoordinationReadUnavailable, StaleRevision, TranscriptChanged
from textual.worker import Worker, WorkerCancelled
from textual.await_complete import AwaitComplete
from toad.widgets.history_anchor import HeldReaderDestination

if TYPE_CHECKING:
    from toad.screens.session_view import SessionOrigin, SessionView
    from toad.widgets.conversation import Conversation
    from toad.widgets.transcript_history import TranscriptHistory
    from toad.transcript_preparation import PreparedPageSource


@dataclass(frozen=True)
class BoundFrame:
    binding: BoundView
    owner: TranscriptPresentation
    generation: int
    @classmethod
    def capture(cls, binding, owner, *args, **extra):
        return cls(binding, owner, owner.generation, *args, **extra)

    def current(self):
        return (self.owner.binding is self.binding
                and self.owner.generation == self.generation
                and self.binding.current())

    def painted(self, cursor):
        if self.current():
            self.owner.displayed_cursor = cursor
            self.binding.contents.check_notifications()
            view = self.binding.view
            view.app.history_displayed()
            view.settle_user_message()


class TranscriptPublication(BoundFrame, ABC):
    """Holds the source, resources and generation for one read and publication."""

    def __init__(self, binding: BoundView, owner: TranscriptPresentation, generation: int) -> None:
        super().__init__(binding, owner, generation)
        self.thread_scope = binding.thread_scope
        self.destination = HeldReaderDestination.held(binding.window)
        self.history = next(iter(binding.histories()), None)
        self.captured = binding.view.turns.owner.captured_snapshot(tuple(binding.contents.children))

    def native_current(self) -> bool:
        """Anonymous native output must have settled before the source captured it."""
        from toad.widgets.committed_presentation import CommitParticipant

        return self.current() and all(
            widget.commit_claim.accepts_native(widget, self.captured)
            for widget in self.binding.contents.children if isinstance(widget, CommitParticipant)
        )

    def source_bound(self, cursor: TranscriptCursor) -> TranscriptCursor:
        """The mounted main history retains the native prefix the wire cursor lacks."""
        if self.native_current():
            return cursor
        return cursor.over_native(tuple(history.committed_cursor for history in self.owner.histories
                                        if history in self.captured and history.state.reports_coverage))

    def source_current(self, cursor: TranscriptCursor) -> bool:
        return self.current() and self.source_bound(cursor) == cursor

    def current(self) -> bool:
        return super().current() and self.thread_scope == self.owner.binding.thread_scope

    async def publish(self) -> bool:
        """Wait for the UI to apply queued messages before acquiring their resources.

        Ordered ACP ingress can already report a settled source while its
        original body messages are still queued on the Conversation. Only that
        native pump can certify that those effects have applied. Reads and
        preparation start after the join, with the same actor and generation.
        """
        if not self.current():
            return True
        view = self.binding.view
        pump = view.task
        if asyncio.current_task() is pump:
            # A snapshot notification itself runs on this pump. Its existing
            # source worker must perform the join; waiting here blocks the very
            # messages whose resources the source needs to acquire.
            self.owner.source_requests.submit(self)
            return True
        from agent_comms.errors import UnregisteredThreadError

        try:
            if await self.capture_application():
                return await self.publish_applied()
        except CoordinationReadUnavailable:
            # No source snapshot was acquired. Keep the original operation,
            # mounted history and work slot unchanged until a new observation
            # or the existing preparation completion resumes source work.
            if self.current():
                self.owner.source_requests.defer(self)
                return False
        except (StaleRevision, UnregisteredThreadError):
            # The original backend read lost its source. Every publication
            # declines it here; only a new observation can accept another read.
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
        self.captured = self.binding.view.turns.owner.captured_snapshot(tuple(self.binding.contents.children))
        return True

    async def application_current(self) -> bool:
        """The original native pump attests applied effects at this source cut."""
        if not self.current():
            return False
        view = self.binding.view
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


class CanonicalSourcePublication(MroDispatch, TranscriptPublication):
    """An observed source change refreshes source pages, never appends a notice."""

    async def read_snapshot(self):
        return await self.read_past_history(
            partial(self.binding.reader.updates, *self.thread_scope, self.owner.current_read))

    async def read_past_history(self, read, **whole):
        """What follows the mounted history's end while its source only grew, else the whole latest page."""
        if self.history is not None:
            try:
                return await read(after=self.history.committed_cursor)
            except TranscriptChanged:
                pass  # Another source file replaced the history's.
        return await read(**whole)

    async def publish_applied(self) -> bool:
        if not self.owner.readable:
            return True
        snapshot = await self.read_snapshot()
        handler, = self.handlers_for(snapshot)
        return await handler(snapshot)

    @handles(TranscriptDraftUpdate)
    async def publish_draft(self, snapshot: TranscriptDraftUpdate) -> bool:
        if self.current():
            self.show_draft(snapshot.draft)
            self.owner.current_read = Published(snapshot.identity)
        return True

    def show_draft(self, draft) -> None:
        widget = self.binding.view.cli_draft
        if self.binding.contents.children[-1] is not widget:
            self.binding.contents.move_child(widget, after=-1)
        widget.show(draft)

    @handles(TranscriptSnapshotUpdate)
    async def publish_snapshot(self, snapshot: TranscriptSnapshotUpdate) -> bool:
        page = snapshot.page
        # The known native cut and its applied original resources meet here.
        # An expired application cannot publish this read; it is not a stale
        # backend revision and must not escape as a failed Textual worker.
        if not await self.capture_application():
            return True
        bound = self.source_bound(page.after)
        if bound != page.after:
            self.owner.dirty = self.owner.commit_required = True
            page = await self.owner.get_transcript_page(after=snapshot.identity.after, through=bound)
            # Preserve this cut's original cohort across the bounded read.
            if not await self.application_current():
                return True
        published = await self.publish_source_page(page)
        if self.current():
            self.show_draft(snapshot.draft)
            if published and bound == snapshot.page.after:
                self.owner.current_read = Published(snapshot.identity)
        if published and self.current() and self.destination is not None:
            self.destination.source_settled(self.binding.window)
        return published

    async def publish_source_page(self, page: TranscriptPage) -> bool:
        self.owner.received(page)
        return True


class ObservedSourcePublication(CanonicalSourcePublication):
    def __init__(self, binding, owner, generation, presentation):
        super().__init__(binding, owner, generation)
        self.presentation = presentation
        self.agent = binding.view.agent

    async def read_snapshot(self):
        return await self.read_past_history(
            partial(self.binding.reader.updates, *self.thread_scope, self.owner.current_read),
            read_identity=self.presentation.read_identity)

    async def publish_applied(self) -> bool:
        if self.current() and self.agent is not None and self.binding.view.agent is self.agent:
            await self.agent.observe_thread_presentation(self.presentation)
        if self.current():
            return await super().publish_applied()
        return True


class SourcePublicationRequests:
    """One running read and one coalesced original request, never model state."""

    def __init__(self, owner: TranscriptPresentation):
        self.owner = owner
        self.pending: deque[TranscriptPublication] = deque(maxlen=1)
        self.worker: Worker[None] | None = None
        self.observation = ResourceRelease()

    def request(self, kind: type[TranscriptPublication], *args: object) -> None:
        publication = self.owner.binding.capture(self.owner, kind, *args)
        if publication is None:
            return
        self.submit(publication)

    def submit(self, publication: TranscriptPublication) -> None:
        """Keep the original operation when its caller is the native UI pump."""
        self.pending.append(publication)
        self.resume()

    def defer(self, publication: TranscriptPublication) -> None:
        """Retain a busy original read without replacing newer source work."""
        if not self.pending:
            self.pending.append(publication)
        view = publication.binding.view
        self.observation.close()
        self.observation.enter_context(view.app.coordination_access.observe_thread_changes(
            view, publication.thread_scope, self.resume))

    def resume(self, _event=None) -> bool:
        """Resume kept work only at an existing source/preparation signal."""
        if not self.pending:
            return False
        if self.worker is None or self.worker.is_finished:
            view = self.pending[0].binding.view
            if not view.is_attached:
                return False
            self.observation.close()
            self.worker = view.run_worker(self.publish, group="transcript-source")
        return True

    async def publish(self) -> None:
        while self.pending:
            publication = self.pending.popleft()
            if not await publication.publish():
                return

    def cancel(self) -> Worker[None] | None:
        self.observation.close()
        self.pending.clear()
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.cancel()
        return worker


class CommitPublication(CanonicalSourcePublication):
    def __init__(self, binding, owner, generation):
        from toad.widgets.committed_presentation import commit_plan
        super().__init__(binding, owner, generation)
        self.plan = commit_plan(binding.window)

    async def read_snapshot(self):
        # Mounted history grows by what follows its end; without one the window needs a whole page.
        return await self.read_past_history(partial(self.binding.reader.snapshot, *self.thread_scope))

    def current(self) -> bool:
        return super().current() and self.plan.current(self.binding.window)

    def ready_to_commit(self) -> bool:
        from toad.widgets.committed_presentation import CommitBarrier, CommitParticipant

        if not self.current() or not self.owner.dirty:
            return False
        view = self.binding.view
        if not self.owner.readable:
            return False
        if not self.owner.commit_required and len(self.binding.contents.children) < view.MAX_LIVE_BLOCKS:
            return False
        if any(isinstance(child, CommitBarrier) for child in self.binding.contents.children):
            return False
        potential = tuple(child for child in self.binding.contents.children
                          if child is not self.history and isinstance(child, CommitParticipant))
        return self.plan.ready(self.history) and self.plan.permits(view, potential)

    async def publish_applied(self) -> bool:
        if self.ready_to_commit():
            return await super().publish_applied()
        return True

    def report_failure(self, error: Exception) -> None:
        if self.current():
            self.binding.view.notify(str(error), title="Committed history", severity="error")

    async def publish_source_page(self, page: TranscriptPage) -> bool:
        from toad.widgets.committed_presentation import CommitEvidence, retirement_candidates
        from toad.widgets.transcript_history import TranscriptHistory

        if not self.ready_to_commit():
            return True
        view = self.binding.view
        window, contents = self.binding.window, self.binding.contents
        # A page cannot replace live blocks posted while its read or fragment
        # preparation is in flight unless it explicitly contains their identity.
        plan, history = self.plan, self.history
        is_current = partial(self.source_current, page.after)
        if history is None and not page.events or not is_current():
            return True
        prepared = await plan.prepare(view, history, page, self.captured, is_current)
        if prepared is None or not is_current():
            return True
        evidence = CommitEvidence(
            self.captured, prepared.sequences, prepared.history,
            TranscriptCoverage(page.events).native_inputs,
            prepared.outgoing,
        )
        replacement = None
        if prepared.history is None:
            replacement = TranscriptHistory(
                prepared.page, self.owner.get_transcript_page, committed=False,
                notification_view=contents,
            )
            await contents.prepare_history(
                replacement, is_current, window=window,
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
                    accepted = False
                    try:
                        if replacement is not None:
                            await contents.mount(replacement)
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
            self.owner.commit_required = False
        plan.finish(view, page.after)
        if page.has_newer:
            self.owner.require_commit()
        return True



class ViewBinding(ABC):
    """The native view's binding and its view-dependent operations."""

    def matches(self, view):
        return False

    def bound_to(self, view):
        return BoundView(view)

    @property
    def thread_scope(self):
        return None

    def histories(self):
        return ()

    def observe_thread(self, owner):
        pass

    def capture(self, owner, kind, *args):
        return None

    def painted(self, owner, cursor):
        pass

    def request(self, owner):
        return None

    def cancel_workers(self):
        return ()

    def covered(self, owner, coverage, history):
        return AwaitComplete.nothing()

    def reset_reader(self):
        pass


class NoView(ViewBinding):
    """An unbound document has no native work to perform."""


class BoundView(ViewBinding):
    @dataclass(frozen=True)
    class Moment(BoundFrame):
        source: SessionView

        @classmethod
        def capture(cls, binding, owner, **extra):
            from toad.screens.session_view import SessionView
            return super().capture(binding, owner,
                                   source=binding.view.query_ancestor(SessionView), **extra)

        def current(self):
            return (super().current() and self.source.is_current
                    and self.source in self.binding.view.ancestors)

    @dataclass(frozen=True)
    class Restoration(Moment):
        revision: int

        def current(self):
            return (super().current() and not self.owner.closed
                    and self.binding.window.scroll_revision == self.revision)

        def refresh(self, publication):
            if not self.current():
                return
            if publication is None:
                if (destination := HeldReaderDestination.held(self.binding.window)) is not None:
                    destination.release(self.binding.window)
            else:
                self.owner.source_requests.submit(publication)

    def __init__(self, view: Conversation):
        self.view, self.window, self.contents = view, view.window, view.contents

    def matches(self, view):
        return self.view is view

    def bound_to(self, view):
        if not self.matches(view):
            raise ValueError("Transcript already has a native publisher")
        return self

    @property
    def thread_scope(self):
        view = self.view
        return view.transcript_scope() if view.is_attached else None

    @property
    def reader(self):
        return self.view.app.coordination_access.transcripts

    def current(self):
        return (self.view.is_attached and not self.view.is_leaving
                and self.window.is_attached and self.contents.is_attached)

    def histories(self):
        from toad.widgets.transcript_history import TranscriptHistory
        return tuple(self.contents.query_children(TranscriptHistory))

    def observe_thread(self, owner):
        scope = self.thread_scope
        if scope is not None:
            view = self.view
            owner._thread_observation.enter_context(
                view.app.coordination_access.observe_thread_changes(view, scope, view.thread_observed))

    async def restore_documents(self, owner):
        from toad.widgets.transcript_history import TranscriptHistory
        view = self.view
        if not view.is_attached:
            return
        moment = self.Moment.capture(self, owner)
        contents = self.contents
        for source in owner.documents:
            if not moment.current() or source.closed:
                return
            history = TranscriptHistory.from_source(source, notification_view=contents)
            await contents.prepare_history(history, moment.current, window=self.window)
            if not moment.current():
                return
            accepted = False
            try:
                await contents.mount(history)
                if not moment.current():
                    return
                history.acquire_document()
                owner.documents = tuple(document for document in owner.documents if document is not source)
                accepted = True
            finally:
                if not accepted and history.is_attached:
                    await history.remove()

    async def restore(self, owner):
        view = self.view
        view.resume_retained_history()
        if not owner.readable:
            return
        first_history = next(iter(owner.histories), None)
        moment = self.Restoration.capture(self, owner, revision=view.window.scroll_revision)
        position = self.window.reader_position
        if position is not None:
            for history in owner.histories:
                if not await history.restore_reader_ranges(position.ranges, moment.current):
                    return
        if not moment.current():
            return
        if first_history is not None:
            await self.reveal_retained(owner, first_history)
        view.refresh_native_projection()
        publication = self.capture(owner, CanonicalSourcePublication)
        view.call_after_refresh(partial(moment.refresh, publication))

    async def reveal_retained(self, owner, history):
        from toad.widgets.conversation import ThreadLoading
        from toad.widgets.session_details import SessionDetails
        view = self.view
        if not view.is_attached:
            return
        self.painted(owner, history.committed_cursor)
        if (loading := view.query_one_optional(ThreadLoading)) is not None:
            await loading.remove()
        view.query_one(SessionDetails)._refresh_summary()

    def capture(self, owner, kind, *args):
        view = self.view
        if not view.is_attached or view.is_leaving:
            return None
        return kind.capture(self, owner, *args)

    def painted(self, owner, cursor):
        frame = BoundFrame.capture(self, owner)
        self.view.call_after_refresh(partial(frame.painted, cursor))

    def request(self, owner):
        view = self.view
        if not view.is_attached:
            return None
        owner.worker = view.run_worker(partial(owner.publish, CommitPublication),
                                       group="transcript-window", exclusive=True)
        return owner.worker

    def cancel_workers(self):
        view = self.view
        return tuple(worker for group in ("transcript-window", "transcript-source", "transcript-handling")
                     for worker in view.workers.cancel_group(view, group))

    def covered(self, owner, coverage, history):
        from toad.widgets.session_details import SessionDetails
        from toad.widgets.committed_presentation import (
            CommitEvidence, CommitParticipant, protected_blocks, retirement_candidates,
        )
        view = self.view
        contents = self.contents
        if history.is_attached and history.parent is contents:
            owner.events.publish(coverage)
            candidates = retirement_candidates(contents.children, CommitEvidence(
                frozenset(),
                frozenset(coverage.sequences) | history.covered_sequences(frozenset(
                    sequence for child in contents.children if isinstance(child, CommitParticipant)
                    for sequence in child.commit_claim.required_sequences)),
                history, coverage.native_inputs, history.outgoing_coverage,
            ))
            protected = protected_blocks(view, candidates)
            retirement = owner.retire_presentations(contents, view.output,
                [child for child in candidates if child not in protected])
            async def complete():
                await retirement
                view.query_one(SessionDetails)._refresh_summary()
            return AwaitComplete(complete())
        return AwaitComplete.nothing()

    def reset_reader(self):
        self.window.reader_position = None


class TranscriptPresentation:
    """Owns the transcript document; attached native publishers can be replaced."""

    def __init__(self) -> None:
        self.binding: ViewBinding = NoView()
        self.documents: tuple[PreparedPageSource, ...] = ()
        self.closed = False
        self.generation = 0
        self.dirty = False
        self.commit_required = False
        self.displayed_cursor: TranscriptCursor | None = None
        self.current_read: TranscriptPublicationState = NotPublished()
        self.worker: Worker[None] | None = None
        self.source_requests = SourcePublicationRequests(self)
        self._thread_observation = ResourceRelease()
        from toad.core.events import CoreEventStream
        self.events = CoreEventStream(self)

    def bind(self, view: Conversation) -> None:
        if self.closed:
            raise ValueError("Transcript lifetime has ended")
        binding = self.binding.bound_to(view)
        self.invalidate_publications()
        self.current_read = NotPublished()
        self.binding = binding
        self.bind_thread_observation()

    def bind_thread_observation(self) -> None:
        """Replace the observation when the owning session changes history source."""
        self._thread_observation.close()
        self.binding.observe_thread(self)

    def _unbind_view(self) -> None:
        self._thread_observation.close()
        self.binding = NoView()

    @property
    def readable(self) -> bool:
        return self.binding.thread_scope is not None

    async def get_transcript_page(self, *, before=None, after=None, through=None,
                                  read_identity=None) -> TranscriptPage:
        frame = self.binding.capture(self, BoundFrame)
        scope = self.binding.thread_scope
        if frame is None or scope is None:
            raise ValueError("Transcript paging requires a bound thread")
        page = await frame.binding.reader.page(*scope, before=before, after=after, through=through,
                                      read_identity=read_identity)
        if self.binding.thread_scope != scope:
            raise ValueError("Thread source changed while reading transcript")
        return page

    @property
    def retained_source_bytes(self) -> int:
        return sum(source.retained_source_bytes for source in self.documents)


    @property
    def histories(self) -> tuple[TranscriptHistory, ...]:
        """Main saved sources are direct children of this transcript.

        A body may own pagers for its Markdown or filtered projection. Those
        rendering resources cannot certify this conversation's saved source.
        The parent-child widget tree, rather than a kept pointer, owns this
        relation through provisional mount, replacement, park and disposal.
        """
        return self.binding.histories()

    def received(self, page: TranscriptPage) -> None:
        """A read page resumes parked history; a commit adds what the history lacks."""
        for history in self.histories:
            history.state.validate_snapshot(history, page)
        history = next(iter(self.histories), None)
        if history is None or not history.committed_cursor.contains(page.after):
            self.require_commit()

    @property
    def reports_coverage(self) -> bool:
        return any(history.state.reports_coverage for history in self.histories)

    def covers_outgoing(self, message) -> bool:
        return any(history.covers_outgoing(message) for history in self.histories)

    def covers_input(self, native_id: str | None) -> bool:
        """Whether saved history already draws the input Core started under this identity.

        A page read can reach the saved input before its start notice reaches
        the conversation. Retirement only removes live blocks that exist when
        a page is accepted, so a start arriving afterwards asks here first.
        """
        return any(history.covers_input(native_id) for history in self.histories)

    def invalidate_publications(self) -> None:
        """Revoke in-flight view work without forgetting its published source."""
        self.generation += 1




    async def publish(self, kind: type[TranscriptPublication], *args) -> bool:
        publication = self.binding.capture(self, kind, *args)
        if publication is not None and publication.current():
            return await publication.publish()
        return True

    async def snapshot(self, page: TranscriptPage) -> None:
        self.received(page)


    def changed(self, cursor: TranscriptCursor | None) -> None:
        self.invalidate_publications()
        self.dirty = True
        if cursor is None:
            self.commit_required = True
        else:
            self.binding.painted(self, cursor)
        self.binding.request(self)

    def require_commit(self) -> None:
        self.invalidate_publications()
        self.commit_required = self.dirty = True
        self.binding.request(self)

    async def refresh_cursor(self) -> TranscriptCursor:
        """Commit and return the cursor from the resulting painted transcript."""
        frame = self.binding.capture(self, BoundFrame)
        if frame is None:
            raise TranscriptChanged()
        self.require_commit()
        worker = self.worker
        if worker is None:
            raise TranscriptChanged()
        await worker.wait()
        if self.binding is not frame.binding or not frame.binding.current():
            raise TranscriptChanged()
        ready = asyncio.get_running_loop().create_future()
        frame.binding.view.call_after_refresh(lambda: ready.set_result(self.displayed_cursor))
        cursor = await ready
        if cursor is None:
            raise TranscriptChanged()
        return cursor

    def retry(self) -> None:
        if self.source_requests.resume():
            return
        if not self.dirty or self.worker is not None and not self.worker.is_finished:
            return
        publication = self.binding.capture(self, CommitPublication)
        if publication is not None and publication.native_current() and publication.ready_to_commit():
            self.binding.request(self)

    def source_work_finished(self, history) -> None:
        if history in self.histories:
            self.retry()

    async def close(self) -> None:
        self.closed = True
        try:
            async with AsyncResourceRelease() as release:
                for history in reversed(tuple(self.histories)):
                    release.callback(history.close)
                release.callback(self._close_documents)
                await self.suspend()
        finally:
            self._unbind_view()
            self.displayed_cursor = None

    def _close_documents(self) -> None:
        documents, self.documents = self.documents, ()
        with ResourceRelease() as release:
            for source in reversed(documents):
                release.callback(source.close)

    async def detach(self, view: Conversation) -> None:
        """A view-owned transcript has no remaining consumer after detach."""
        if self.binding.matches(view):
            await self.close()

    async def suspend(self) -> None:
        """Revoke in-flight publications while retaining this source's mounted frontier."""
        self.invalidate_publications()
        worker, self.worker = self.worker, None
        workers = [worker, self.source_requests.cancel()]
        workers.extend(self.binding.cancel_workers())
        for worker in workers:
            if worker is None:
                continue
            worker.cancel()
            try:
                await worker.wait()
            except WorkerCancelled:
                pass


    def retire_presentations(self, contents, output, candidates) -> AwaitComplete:
        """Withdraw covered native paint now; join teardown outside source locks.

        CommitEvidence has already selected these exact resources. Their native
        display lifetime ends synchronously, so accepted saved rows cannot paint
        alongside them while an original stream finishes its paged publication.
        The separate teardown task handles cancellation; source transactions
        register its completion outside their mutation locks.
        """
        if not candidates:
            return AwaitComplete.nothing()
        from toad.widgets.history_anchor import HistoryWindow

        if any(candidate.display for candidate in candidates):
            # Their rows leave the window now; the reader stays on theirs.
            contents.query_ancestor(HistoryWindow).keep_reader()
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


class SessionTranscriptPresentation(TranscriptPresentation):
    """The operational session retains its source after native view eviction."""

    @asynccontextmanager
    async def changing_source(self, origin: SessionOrigin):
        """Replace source resources when the logical session changes source.

        The origin also exists while its native view is evicted. Connection
        creation, attachment and readiness do not replace that history source.
        """
        previous = origin.transcript_scope()
        try:
            yield
        finally:
            if origin.transcript_scope() != previous:
                self.bind_thread_observation()
                self.source_requests.cancel()
                self.invalidate_publications()
                self.current_read = NotPublished()
                self._close_documents()
                self.dirty = self.commit_required = False
                self.displayed_cursor = None
                worker, self.worker = self.worker, None
                if worker is not None:
                    worker.cancel()
                # A different origin does not authorize reusing these pages.
                # Withdraw every old source before joining any cancelled work.
                retirement = AwaitComplete(*(history.retire_source()
                                             for history in self.histories))
                self.binding.reset_reader()
                await retirement

    async def detach(self, view: Conversation) -> None:
        if not self.binding.matches(view):
            return
        self._thread_observation.close()
        await self.suspend()
        if self.closed or not self.binding.matches(view):
            return
        generation = self.generation
        documents = []
        for history in self.histories:
            if history._source_state.retirement_source().reports_coverage:
                documents.append(await history.park_document())
                if self.closed or not self.binding.matches(view) or self.generation != generation:
                    for source in documents:
                        source.close()
                    return
        self._close_documents()
        self.documents = tuple(documents)
        self._unbind_view()
        self.displayed_cursor = None
