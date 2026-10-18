"""Source-fenced saved transcript publication; commit policy stays declared."""
from __future__ import annotations

import weakref
import asyncio
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack, asynccontextmanager
from toad.resource_release import AsyncResourceRelease, ResourceRelease
from functools import partial
from typing import TYPE_CHECKING

from agent_comms.transcripts import TranscriptCursor, TranscriptPage, TranscriptReadIdentity
from agent_comms.transcript_events import TranscriptCoverage
from agent_comms.acp_extension import TranscriptDraftUpdate, TranscriptSnapshotUpdate
from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.coordination_errors import CoordinationReadUnavailable, StaleRevision, TranscriptChanged
from textual.worker import Worker, WorkerCancelled
from textual.await_complete import AwaitComplete
from toad.widgets.history_anchor import HeldReaderDestination

if TYPE_CHECKING:
    from toad.screens.session_view import SessionOrigin
    from toad.widgets.conversation import Conversation, Window, Contents
    from toad.widgets.transcript_history import TranscriptHistory
    from toad.transcript_preparation import PreparedPageSource


class TranscriptPublication(ABC):
    """Holds the source, resources and generation for one read and publication."""

    def __init__(self, owner: TranscriptPresentation, view: Conversation,
                 window: Window, contents: Contents) -> None:
        self.owner = owner
        self.generation = owner.generation
        self.thread_scope = owner.thread_scope
        self.window, self.contents = window, contents
        self.destination = HeldReaderDestination.held(window)
        self.history = next(iter(owner.histories), None)
        self.captured = view.turns.owner.captured_snapshot(tuple(contents.children))

    def native_current(self) -> bool:
        """Anonymous native output must have settled before the source captured it."""
        from toad.widgets.committed_presentation import CommitParticipant

        return self.current() and all(
            widget.commit_claim.accepts_native(widget, self.captured)
            for widget in self.contents.children if isinstance(widget, CommitParticipant)
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
        from toad.widgets.conversation import Window, Contents
        view = self.owner.view
        if view is None or not view.is_attached or view.is_leaving:
            return False
        if (self.generation != self.owner.generation
                or self.thread_scope != self.owner.thread_scope):
            return False
        return (self.window.is_attached and self.contents.is_attached
                and view.query_one_optional(Window) is self.window
                and view.query_one_optional(Contents) is self.contents)

    async def publish(self) -> bool:
        """Wait for the UI to apply queued messages before acquiring their resources.

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


class HandlingPublication(TranscriptPublication):
    """Render original recipient outcomes on existing original source bodies."""

    async def publish_applied(self) -> bool:
        from toad.widgets.wire_message_handling import WireMessageHandling

        bodies = WireMessageHandling.within(self.contents)
        if not self.owner.readable:
            return True
        references = WireMessageHandling.references_in(bodies)
        if not references:
            return True
        results = await self.owner.get_message_notifications(references)
        if self.current():
            for body in bodies:
                if body.is_attached:
                    body.show_notifications(results)
        return True


class CanonicalSourcePublication(MroDispatch, TranscriptPublication):
    """An observed source change refreshes source pages, never appends a notice."""

    async def read_snapshot(self):
        return await self.read_past_history(
            partial(self.owner.reader.updates, *self.thread_scope, self.owner.current_read))

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
            self.owner.current_read = snapshot.identity
        return True

    def show_draft(self, draft) -> None:
        widget = self.owner.view.cli_draft
        if self.contents.children[-1] is not widget:
            self.contents.move_child(widget, after=-1)
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
                self.owner.current_read = snapshot.identity
        if published and self.current() and self.destination is not None:
            self.destination.source_settled(self.window)
        return published

    async def publish_source_page(self, page: TranscriptPage) -> bool:
        self.owner.received(page)
        return await self.owner.publish(HandlingPublication)


class ObservedSourcePublication(CanonicalSourcePublication):
    def __init__(self, owner, view, window, contents, presentation):
        super().__init__(owner, view, window, contents)
        self.presentation = presentation
        self.agent = view.agent

    async def read_snapshot(self):
        return await self.read_past_history(
            partial(self.owner.reader.updates, *self.thread_scope, self.owner.current_read),
            read_identity=self.presentation.read_identity)

    async def publish_applied(self) -> bool:
        view = self.owner.view
        if view is not None and self.agent is not None and view.agent is self.agent:
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
        self.observation = ResourceRelease()

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
        if view is None:
            return
        self.observation.close()
        self.observation.enter_context(view.app.coordination_access.observe_thread_changes(
            view, publication.thread_scope, self.resume))

    def resume(self, _event=None) -> bool:
        """Resume kept work only at an existing source/preparation signal."""
        if self.pending.empty():
            return False
        if self.worker is None or self.worker.is_finished:
            view = self.owner.view
            if view is None or not view.is_attached:
                return False
            self.observation.close()
            self.worker = view.run_worker(self.publish, group="transcript-source")
        return True

    async def publish(self) -> None:
        while not self.pending.empty():
            publication = self.pending.get_nowait()
            if not await publication.publish():
                return

    def cancel(self) -> Worker[None] | None:
        self.observation.close()
        while not self.pending.empty():
            self.pending.get_nowait()
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.cancel()
        return worker


class CommitPublication(CanonicalSourcePublication):
    def __init__(self, owner, view, window, contents):
        from toad.widgets.committed_presentation import commit_plan
        super().__init__(owner, view, window, contents)
        self.plan = commit_plan(window)

    async def read_snapshot(self):
        # Mounted history grows by what follows its end; without one the window needs a whole page.
        return await self.read_past_history(partial(self.owner.reader.snapshot, *self.thread_scope))

    def current(self) -> bool:
        view = self.owner.view
        return (super().current() and not view.is_leaving
                and self.plan.current(self.window))

    def ready_to_commit(self) -> bool:
        from toad.widgets.committed_presentation import CommitBarrier, CommitParticipant

        view = self.owner.view
        if not self.current() or not self.owner.dirty:
            return False
        if not self.owner.readable:
            return False
        if not self.owner.commit_required and len(self.contents.children) < view.MAX_LIVE_BLOCKS:
            return False
        if any(isinstance(child, CommitBarrier) for child in self.contents.children):
            return False
        potential = tuple(child for child in self.contents.children
                          if child is not self.history and isinstance(child, CommitParticipant))
        return self.plan.ready(self.history) and self.plan.permits(view, potential)

    async def publish_applied(self) -> bool:
        if self.ready_to_commit():
            return await super().publish_applied()
        return True

    def report_failure(self, error: Exception) -> None:
        if self.current():
            self.owner.view.notify(str(error), title="Committed history", severity="error")

    async def publish_source_page(self, page: TranscriptPage) -> bool:
        from toad.widgets.committed_presentation import CommitEvidence, retirement_candidates
        from toad.widgets.transcript_history import TranscriptHistory

        view = self.owner.view
        if view is None:
            return True
        window, contents = self.window, self.contents
        if not self.ready_to_commit():
            return True
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



class TranscriptPresentation:
    """Owns the transcript document; attached native publishers can be replaced."""

    def __init__(self, view: Conversation | None = None) -> None:
        self._view = weakref.ref(view) if view is not None else lambda: None
        self.documents: tuple[PreparedPageSource, ...] = ()
        self.closed = False
        self.generation = 0
        self.dirty = False
        self.commit_required = False
        self.displayed_cursor: TranscriptCursor | None = None
        self.current_read: TranscriptReadIdentity | None = None
        self.worker: Worker[None] | None = None
        self.source_requests = SourcePublicationRequests(self)
        self._thread_observation = ResourceRelease()
        from toad.core.events import CoreEventStream
        self.events = CoreEventStream(self)

    @property
    def view(self) -> Conversation | None:
        return self._view()

    def bind(self, view: Conversation) -> None:
        if self.closed:
            raise ValueError("Transcript lifetime has ended")
        if self.view is not None and self.view is not view:
            raise ValueError("Transcript already has a native publisher")
        self.invalidate_publications()
        self.current_read = None
        self._view = weakref.ref(view)

    @property
    def thread_scope(self) -> tuple[str, str] | None:
        """The view declares the thread whose main history it presents."""
        view = self.view
        return view.transcript_scope() if view is not None and view.is_attached else None

    def bind_thread_observation(self) -> None:
        """Replace the observation when the owning session changes history source."""
        self._thread_observation.close()
        scope = self.thread_scope
        if scope is not None:
            view = self.view
            self._thread_observation.enter_context(
                view.app.coordination_access.observe_thread_changes(
                    view, scope, view._thread_rows_changed))

    def _unbind_view(self) -> None:
        self._thread_observation.close()
        self._view = lambda: None

    @property
    def readable(self) -> bool:
        return self.thread_scope is not None

    @property
    def reader(self):
        view = self.view
        if view is None:
            raise ValueError("Transcript reader requires a bound view")
        return view.app.coordination_access.transcripts

    async def get_transcript_page(self, *, before=None, after=None, through=None,
                                  read_identity=None) -> TranscriptPage:
        scope = self.thread_scope
        if scope is None:
            raise ValueError("Transcript paging requires a bound thread")
        page = await self.reader.page(*scope, before=before, after=after, through=through,
                                      read_identity=read_identity)
        if self.thread_scope != scope:
            raise ValueError("Thread source changed while reading transcript")
        return page

    async def get_message_notifications(self, references):
        scope = self.thread_scope
        if scope is None:
            raise ValueError("Notification reads require a bound thread")
        results = await self.reader.notifications(scope[0], references)
        if self.thread_scope != scope:
            raise ValueError("Thread source changed during notification read")
        return results

    @property
    def retained_source_bytes(self) -> int:
        return sum(source.retained_source_bytes for source in self.documents)

    async def restore_documents(self) -> None:
        """Transfer original prepared data back to native consumers, without a read."""
        from toad.widgets.transcript_history import TranscriptHistory
        from toad.screens.session_view import SessionView

        view = self.view
        if view is None or not view.is_attached:
            return
        generation, window, contents, screen = self.generation, view.window, view.contents, view.screen
        source_view = view.query_ancestor(SessionView)
        def current():
            return (self.view is view and view.is_attached and not view.is_leaving
                    and self.generation == generation
                    and view.window is window and view.contents is contents
                    and view.screen is screen and screen.is_current
                    and view.app.workspace_sessions.owns(source_view))

        for source in self.documents:
            if not current() or source.closed:
                return
            history = TranscriptHistory.from_source(source)
            await contents.prepare_history(
                history, current, window=window,
            )
            if not current():
                return
            accepted = False
            try:
                await contents.mount(history)
                if not current():
                    return
                history.acquire_document()
                self.documents = tuple(document for document in self.documents if document is not source)
                accepted = True
            finally:
                if not accepted and history.is_attached:
                    await history.remove()

    @property
    def histories(self) -> tuple[TranscriptHistory, ...]:
        """Main saved sources are direct children of this transcript.

        A body may own pagers for its Markdown or filtered projection. Those
        rendering resources cannot certify this conversation's saved source.
        The parent-child widget tree, rather than a kept pointer, owns this
        relation through provisional mount, replacement, park and disposal.
        """
        from toad.widgets.transcript_history import TranscriptHistory
        from toad.widgets.conversation import Contents

        view = self.view
        if view is None:
            return ()
        # Mount and prune own the native container's lifetime. A logical source
        # can bind before that mount and close after prune; neither state has a
        # live pager. Required content access belongs to actual publication.
        contents = view.query_one_optional(Contents)
        return tuple(contents.query_children(TranscriptHistory)) if contents is not None else ()

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

    async def restore(self) -> None:
        """Restore the session's reader independently of native attachment readiness."""
        from toad.screens.session_view import SessionView

        view = self.view
        if view is None:
            return
        view.resume_retained_history()
        if not self.readable:
            return
        await self.restore_documents()
        first_history = next(iter(self.histories), None)
        source = view.query_ancestor(SessionView)
        generation, window, contents = self.generation, view.window, view.contents
        # The place the reader left with the tab; reaching it is not the reader moving.
        position, revision, screen = window.reader_position, window.scroll_revision, view.screen

        def current():
            return (self.view is view and view.is_attached and not view.is_leaving and not self.closed
                    and self.generation == generation
                    and view.window is window and view.contents is contents
                    and window.is_attached and contents.is_attached
                    and window.scroll_revision == revision
                    and view.screen is screen and screen.is_current
                    and view.query_ancestor(SessionView) is source
                    and view.app.workspace_sessions.owns(source))

        if position is not None:
            for history in self.histories:
                if not await history.restore_reader_ranges(position.ranges, current):
                    return
        if not current():
            return
        if first_history is not None:
            await self.reveal_retained(first_history)
        view.refresh_native_projection()
        publication = self.capture(CanonicalSourcePublication)

        def refresh_after_paint() -> None:
            if not current():
                return
            if publication is None:
                if (destination := HeldReaderDestination.held(window)) is not None:
                    destination.release(window)
                return
            self.source_requests.submit(publication)

        view.call_after_refresh(refresh_after_paint)

    async def reveal_retained(self, history: TranscriptHistory) -> None:
        """Display the mounted reader while its native source remains fenced."""
        from toad.widgets.conversation import ThreadLoading
        from toad.widgets.session_details import SessionDetails

        view = self.view
        if view is None or not view.is_attached:
            return
        self.painted(history.committed_cursor)
        if (loading := view.query_one_optional(ThreadLoading)) is not None:
            await loading.remove()
        view.query_one(SessionDetails)._refresh_summary()

    def capture(self, kind: type[TranscriptPublication], *args) -> TranscriptPublication | None:
        """Accept an operation bound to its original attachment and acquired resources."""
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
        self.received(page)

    def painted(self, cursor: TranscriptCursor) -> None:
        from toad.widgets.conversation import Window, Contents
        view = self.view
        if view is None:
            return
        generation = self.generation
        window, contents = view.query_one_optional(Window), view.query_one_optional(Contents)
        def record() -> None:
            if self.view is not view or not view.is_attached:
                return
            if self.generation != generation:
                return
            if window is None or contents is None:
                return
            if window.is_attached and contents.is_attached:
                self.displayed_cursor = cursor
                view.app.history_displayed()
                view.settle_user_message()
        view.call_after_refresh(record)

    def changed(self, cursor: TranscriptCursor | None) -> None:
        self.invalidate_publications()
        self.dirty = True
        if cursor is None:
            self.commit_required = True
        else:
            self.painted(cursor)
        self.request()

    def require_commit(self) -> None:
        self.invalidate_publications()
        self.commit_required = self.dirty = True
        self.request()

    def request(self) -> Worker[None] | None:
        if (view := self.view) is None or not view.is_attached:
            return None
        self.worker = view.run_worker(partial(self.publish, CommitPublication),
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
        publication = self.capture(CommitPublication)
        if publication is not None and publication.native_current() and publication.ready_to_commit():
            self.request()

    def source_work_finished(self, history) -> None:
        if history in self.histories:
            self.retry()

    async def close(self) -> None:
        self.closed = True
        try:
            async with AsyncResourceRelease() as release:
                for history in reversed(tuple(self.histories)):
                    if history._page_buffer is not None:
                        release.callback(history._page_buffer.close)
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
        if self.view is view:
            await self.close()

    async def suspend(self) -> None:
        """Revoke in-flight publications while retaining this source's mounted frontier."""
        self.invalidate_publications()
        worker, self.worker = self.worker, None
        workers = [worker, self.source_requests.cancel()]
        if (view := self.view) is not None:
            # Exclusive replacement/cancel can detach the current handle while
            # an older accepted publication still joins its retirement. The
            # framework manager owns those actual tasks until completion.
            workers.extend(view.workers.cancel_group(view, "transcript-window"))
            workers.extend(view.workers.cancel_group(view, "transcript-source"))
            workers.extend(view.workers.cancel_group(view, "transcript-handling"))
        for worker in workers:
            if worker is None:
                continue
            worker.cancel()
            try:
                await worker.wait()
            except WorkerCancelled:
                pass

    def covered(self, coverage, history) -> AwaitComplete:
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
            and history.is_attached
            and history.parent is contents
        ):
            self.events.publish(coverage)
            candidates = retirement_candidates(
                contents.children,
                CommitEvidence(
                    frozenset(),
                    frozenset(coverage.sequences) | history.covered_sequences(
                        frozenset(sequence for child in contents.children
                                  if isinstance(child, CommitParticipant)
                                  for sequence in child.commit_claim.required_sequences)),
                    history,
                    coverage.native_inputs,
                    history.outgoing_coverage,
                ),
            )
            protected = protected_blocks(view, candidates)
            retirement = self.retire_presentations(contents, view.output,
                [child for child in candidates if child not in protected])

            async def complete() -> None:
                await retirement
                # The accepted frontier also invalidates its existing status view.
                # A kept resume can reject an identical snapshot without any
                # widget replacement; it still publishes main coverage here.
                view.query_one(SessionDetails)._refresh_summary()
                if view.thread_presentation is not None:
                    view.run_worker(partial(self.publish, HandlingPublication),
                                    group="transcript-handling", exclusive=True)

            return AwaitComplete(complete())
        return AwaitComplete.nothing()

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
                self.current_read = None
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
                from toad.widgets.conversation import Window
                view = self.view
                if view is not None and (window := view.query_one_optional(Window)) is not None:
                    window.reader_position = None
                await retirement

    async def detach(self, view: Conversation) -> None:
        if self.view is not view:
            return
        await self.suspend()
        if self.closed or self.view is not view:
            return
        generation = self.generation
        documents = []
        for history in self.histories:
            if history._source_state.retirement_source().reports_coverage:
                documents.append(await history.park_document())
                if self.closed or self.view is not view or self.generation != generation:
                    for source in documents:
                        source.close()
                    return
        self._close_documents()
        self.documents = tuple(documents)
        self._unbind_view()
        self.displayed_cursor = None
