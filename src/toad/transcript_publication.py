"""Source-fenced saved transcript publication; commit policy stays declared."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING, Self, TypeGuard

from agent_comms.acp_extension import (
    InputStartedUpdate,
    TranscriptDraftUpdate,
    TranscriptSnapshotUpdate,
)
from agent_comms.child_process import join_retirement
from agent_comms.coordination.errors import (
    CoordinationReadUnavailable,
    ReadAgain,
    ReloadRequired,
    StaleRevision,
    TranscriptChanged,
)
from agent_comms.external_transcript import DraftRow
from agent_comms.transcript_sources import NoDraft
from metaclass_registry.mro_dispatch import MroDispatch, handles
from agent_comms.sent_message import PublishedSentMessage
from agent_comms.registry.thread_presentation import ThreadPresentation
from agent_comms.transcript_events import TranscriptCoverage
from agent_comms.transcripts import (
    AtFrontier,
    LatestPage,
    PageLimit,
    PagePosition,
    Through,
    TranscriptCursor,
    TranscriptPage,
    TranscriptReadIdentity,
    UnreadTranscriptCursor,
)
from agent_comms.ui_model.observation import (
    NotPublished,
    Published,
    TranscriptPublicationState,
)
from textual.await_complete import AwaitComplete
from textual.widget import Widget
from textual.worker import Worker, WorkerCancelled, get_current_worker

from toad.core.events import CoreEventStream, ThreadRowsChanged
from toad.core.projection import MroProjection
from toad.core.source_events import TranscriptCoverage as CoverageEvent
from toad.history_coverage import NO_COVERAGE, HistoryCoverage
from toad.resource_release import AsyncResourceRelease, ResourceRelease
from toad.worker_group import WorkerGroup
from toad.screens.session_view import SessionView
from toad.session_scope import (
    NoTranscript,
    SessionOrigin,
    SessionScope,
    TranscriptScope,
)
from toad.transcript_preparation import PreparedPageSource
from toad.widgets.committed_presentation import block_claim, commit_plan, protected_blocks, retirement_candidates
from toad.commit_claims import CommitEvidence, NativeCommitEvidence
from toad.widgets.history_anchor import (
    HistoryWindow,
    TailPosition,
)
from toad.widgets.session_details import SessionDetails
from toad.widgets.transcript_history import TranscriptHistory
from toad.live_output import LiveOutput
from toad.widgets.cli_draft import CliDraft
from toad.widgets.transcript_history import CommittedHistory

if TYPE_CHECKING:
    from toad.widgets.conversation import (
        Contents,
        Conversation,
        ConversationSessionBinding,
    )


@dataclass(frozen=True)
class BoundFrame:
    binding: BoundView
    owner: TranscriptPresentation
    generation: int

    @classmethod
    def capture(cls, binding: BoundView, owner: TranscriptPresentation, *args, **extra) -> Self:
        return cls(binding, owner, owner.generation, *args, **extra)

    def current(self):
        return (
            self.owner.binding is self.binding
            and self.owner.generation == self.generation
            and self.binding.current()
        )

    async def read_page(self, scope, *, position: PagePosition, limit: PageLimit) -> TranscriptPage:
        return await self.binding.reader.page(scope, position=position, limit=limit)

    def after_refresh(self, callback: Callable[[], object]) -> None:
        self.binding.view.call_after_refresh(callback)

    def painted(self, cursor: TranscriptCursor) -> None:
        if self.current():
            view = self.binding.view
            view.retire_loading_splash()
            self.owner.displayed_cursor = cursor
            view.app.history_displayed()
            view.query_ancestor(SessionView).history_painted()
            view.submissions.settle()


class DraftPresentation(MroProjection[None]):
    """The CLI draft row draws a native draft and clears when Core reports none."""

    @handles(DraftRow)
    def draft(self, draft: DraftRow, widget: CliDraft, identity: TranscriptReadIdentity) -> None:
        widget.show(draft, resolve_sent=identity.wire_frontier.resolve_sent_messages)

    @handles(NoDraft)
    def none(self, draft: NoDraft, widget: CliDraft, identity: TranscriptReadIdentity) -> None:
        widget.clear()


DRAFT_PRESENTATION = DraftPresentation()


class TranscriptPublication(BoundFrame, ABC):
    """Holds the source, resources and generation for one read and publication."""

    def restored(self, owner: TranscriptPresentation, window: HistoryWindow) -> None:
        """A restored tab publishes its source again."""
        owner.source_requests.submit(self)

    def submit_to(self, requests: SourcePublicationRequests) -> None:
        """Queued now; whether it is still current is decided when it publishes."""
        requests.submit(self)

    def __init__(
        self, binding: BoundView, owner: TranscriptPresentation, generation: int
    ) -> None:
        super().__init__(binding, owner, generation)
        self.thread_scope = binding.thread_scope
        self.destination = binding.window.reader_position
        self.identity: TranscriptReadIdentity
        self.capture_cohort()

    def capture_cohort(self) -> None:
        view = self.binding.view
        self.captured = view.turns.owner.captured_snapshot(tuple(self.binding.contents.children))
        self.native_frontier = view.agent_binding.committed_native_output

    def native_current(self) -> bool:
        """Each captured presentation must belong to the acquired saved prefix."""
        return self.current() and all(
            block_claim(widget).accepts_native(widget, self.captured, self.identity)
            for widget in self.binding.contents.children
        )

    def source_bound(self, cursor: TranscriptCursor) -> TranscriptCursor:
        """The mounted main history retains the native prefix the wire cursor lacks."""
        if self.native_current() and not self.binding.view.turns.owner.busy:
            return cursor
        history = self.binding.history
        retained = history.state.coverage.retained_through(history) if history in self.captured else ()
        source = self.native_frontier
        certified = source.prefixes(self.identity, cursor)
        committed = cursor.over_native(retained + certified)
        # A committed round may cover several bounded pages. Its proof allows
        # this whole page; it cannot enlarge the page we are publishing.
        return cursor if cursor.within(committed) else committed

    def source_current(self, cursor: TranscriptCursor) -> bool:
        return self.current() and self.source_bound(cursor) == cursor

    def current(self) -> bool:
        return (
            super().current() and self.thread_scope == self.owner.binding.thread_scope
        )

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

        try:
            if await self.capture_application():
                return await self.publish_applied()
        except CoordinationReadUnavailable, StaleRevision:
            # No usable source snapshot was acquired. Keep the original operation,
            # mounted history and work slot unchanged until a new observation
            # or the existing preparation completion resumes source work.
            if self.current():
                self.owner.source_requests.defer(self)
                return False
        except ReloadRequired:
            # The published witness names a source that is gone, so resending it never
            # answers: the resumed operation reads from fresh bounds.
            if self.current():
                self.owner.current_read = NotPublished()
                self.owner.source_requests.defer(self)
                return False
        return True

    async def capture_application(self) -> bool:
        """Capture the original applied cohort once its source cut is known."""
        if not await self.application_current():
            return False
        self.capture_cohort()
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

    def __init__(self, binding: BoundView, owner: TranscriptPresentation, generation: int) -> None:
        super().__init__(binding, owner, generation)
        self.plan = commit_plan(binding.window)

    async def read_snapshot(self):
        return await self.plan.read_snapshot(
            partial(
                self.binding.reader.updates, self.thread_scope, self.owner.current_read
            ),
            self.binding.history,
        )

    async def publish_applied(self) -> bool:
        if not self.owner.readable:
            return True
        snapshot = await self.read_snapshot()
        (handler,) = self.handlers_for(snapshot)
        return await handler(snapshot)

    @handles(TranscriptDraftUpdate)
    async def publish_draft(self, snapshot: TranscriptDraftUpdate) -> bool:
        if self.current():
            self.show_draft(snapshot.draft, snapshot.identity)
            self.owner.current_read = Published(snapshot.identity)
        return True

    def show_draft(self, draft: DraftRow | NoDraft, identity: TranscriptReadIdentity) -> None:
        widget = self.binding.view.cli_draft
        if self.binding.contents.children[-1] is not widget:
            self.binding.contents.move_child(widget, after=-1)
        DRAFT_PRESENTATION.project_value(draft, widget, identity)

    @handles(TranscriptSnapshotUpdate)
    async def publish_snapshot(self, snapshot: TranscriptSnapshotUpdate) -> bool:
        page = snapshot.page
        self.identity = snapshot.identity
        # The known native cut and its applied original resources meet here.
        # An expired application cannot publish this read; it is not a stale
        # backend revision and must not escape as a failed Textual worker.
        if not await self.capture_application():
            return True
        bound = self.source_bound(page.after)
        if bound != page.after:
            self.owner.demand = COMMIT_DEMAND
            page = await self.owner.get_transcript_page(
                position=snapshot.identity.position.later_only(), limit=Through(bound)
            )
            # Preserve this cut's original cohort across the bounded read.
            if not await self.application_current():
                return True
        published = await self.publish_source_page(page)
        if self.current():
            self.show_draft(snapshot.draft, snapshot.identity)
            if published and bound == snapshot.page.after:
                self.owner.current_read = Published(snapshot.identity)
        if published and self.current():
            self.destination.source_settled(self.binding.window)
        return published

    async def publish_source_page(self, page: TranscriptPage) -> bool:
        self.owner.received(page)
        return True


class ObservedSourcePublication(CanonicalSourcePublication):
    def __init__(self, binding: BoundView, owner: TranscriptPresentation,
                 generation: int, presentation: ThreadPresentation) -> None:
        super().__init__(binding, owner, generation)
        self.presentation = presentation
        self.agent_binding = binding.view.agent_binding

    async def publish_applied(self) -> bool:
        if self.current() and self.binding.view.agent_binding is self.agent_binding:
            await self.agent_binding.observe_thread_presentation(self.presentation)
        if self.current():
            return await super().publish_applied()
        return True


class Uncaptured:
    """What a view that cannot publish captures: never current, never ready to commit, no reader."""

    def current(self) -> bool:
        return False

    def ready_to_commit(self) -> bool:
        return False

    async def read_page(self, scope, *, position: PagePosition, limit: PageLimit) -> TranscriptPage:
        # A page request queued before the view lost its binding: its answer no longer
        # stands, and the request a new binding makes reads again.
        raise ReadAgain()

    async def publish(self) -> bool:
        """Nothing to publish: the request is done."""
        return True

    def after_refresh(self, callback: Callable[[], object]) -> None:
        """No view refreshes; a caller checked currency first and never reaches this."""
        raise TranscriptChanged()

    def restored(self, owner: TranscriptPresentation, window: HistoryWindow) -> None:
        """A restored tab with nothing to publish lets its reader's held place go."""
        window.reader_position.release(window)

    def submit_to(self, requests: SourcePublicationRequests) -> None:
        """Nothing to publish is never queued."""


UNCAPTURED = Uncaptured()


class PublicationWork:
    """No publication is running: nothing to cancel or join, and a commit has nothing to settle."""

    @property
    def is_finished(self) -> bool:
        return True

    def runs(self, worker: Worker) -> bool:
        return False

    def cancel(self) -> None:
        pass

    async def joined(self) -> None:
        """Cancel this work and wait until it has stopped."""

    async def settled(self) -> None:
        """Wait for the commit this work publishes; with none running, the transcript moved on."""
        raise TranscriptChanged()


NO_PUBLICATION_WORK = PublicationWork()


@dataclass(frozen=True)
class RunningPublicationWork(PublicationWork):
    worker: Worker[None]

    @property
    def is_finished(self) -> bool:
        return self.worker.is_finished

    def runs(self, worker: Worker) -> bool:
        return worker is self.worker

    def cancel(self) -> None:
        self.worker.cancel()

    async def joined(self) -> None:
        self.worker.cancel()
        try:
            await self.worker.wait()
        except WorkerCancelled:
            pass

    async def settled(self) -> None:
        await self.worker.wait()



class StartedPublicationWork(WorkerGroup, RunningPublicationWork):
    """A publication worker of one kind, started and joined through that kind."""

    @classmethod
    def start(cls, view: Widget, task: Callable[[], object]) -> Self:
        return cls(cls.run_on(view, task))

    @classmethod
    def cancelled_work(cls, view: Widget) -> tuple[Self, ...]:
        return tuple(map(cls, cls.cancel_all(view)))


class WindowPublicationWork(StartedPublicationWork):
    """Publishes the window's commits; a newer request supersedes a running one."""

    exclusive = True


class SourcePublicationWork(StartedPublicationWork):
    """Reads the queued source publications in order."""



class SourcePublicationRequests:
    """One running read and one coalesced original request, never model state."""

    def __init__(self, owner: TranscriptPresentation) -> None:
        self.owner = owner
        self.pending: deque[TranscriptPublication] = deque(maxlen=1)
        self.worker: PublicationWork = NO_PUBLICATION_WORK
        self.observation = ResourceRelease()

    def request(self, kind: type[TranscriptPublication], *args: ThreadPresentation) -> None:
        self.owner.binding.capture(self.owner, kind, *args).submit_to(self)

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
        self.observation.enter_context(
            publication.thread_scope.observe(
                view, view.app.coordination_access, self.thread_rows_changed
            )
        )

    def thread_rows_changed(self, _change: ThreadRowsChanged) -> None:
        """A subscription only borrows its callback, so this owner holds it as a bound method."""
        self.resume()

    def resume(self) -> bool:
        """Resume kept work only at an existing source/preparation signal."""
        if not self.pending:
            return False
        if self.worker.is_finished:
            view = self.pending[0].binding.view
            if not view.is_attached:
                return False
            self.observation.close()
            self.worker = SourcePublicationWork.start(view, self.publish)
        return True

    async def publish(self) -> None:
        while self.pending:
            publication = self.pending.popleft()
            if not await publication.publish():
                return

    def cancel(self) -> PublicationWork:
        self.observation.close()
        self.pending.clear()
        work, self.worker = self.worker, NO_PUBLICATION_WORK
        work.cancel()
        return work


class CommitPublication(CanonicalSourcePublication):
    async def read_snapshot(self):
        return await self.plan.read_snapshot(
            partial(self.binding.reader.snapshot, self.thread_scope),
            self.binding.history,
        )

    def current(self) -> bool:
        return super().current() and self.plan.current(self.binding.window)

    def ready_to_commit(self) -> bool:
        if not self.current() or not self.owner.readable:
            return False
        view = self.binding.view
        if not self.owner.demand.commits(len(self.binding.contents.children), view.MAX_LIVE_BLOCKS):
            return False
        if any(block_claim(child).blocks_commit for child in self.binding.contents.children):
            return False
        potential = tuple(
            child
            for child in self.binding.contents.children
            if child is not self.binding.history and block_claim(child).retires
        )
        return self.plan.ready(self.binding.history) and self.plan.permits(
            view, potential
        )

    async def publish_applied(self) -> bool:
        if self.ready_to_commit():
            return await super().publish_applied()
        return True

    async def publish_source_page(self, page: TranscriptPage) -> bool:
        if not self.ready_to_commit():
            return True
        view = self.binding.view
        window, contents = self.binding.window, self.binding.contents
        # A page cannot replace live blocks posted while its read or fragment
        # preparation is in flight unless it explicitly contains their identity.
        plan, history = self.plan, self.binding.history
        is_current = partial(self.source_current, page.after)
        if not is_current():
            return True
        prepared = await plan.prepare(view, history, page, self.captured)
        if not is_current():
            return True
        evidence = NativeCommitEvidence(
            self.captured,
            prepared.sequences,
            retained=frozenset({prepared.history}),
            native_inputs=TranscriptCoverage(page.events).native_inputs,
            outgoing=prepared.outgoing,
            identity=replace(self.identity, limit=Through(page.after)),
        )
        retired = retirement_candidates(contents.children, evidence)
        if not plan.permits(view, retired):
            return True
        def publication_current():
            return is_current() and plan.permits(view, retired)

        if not await prepared.draw(page.after, publication_current, tuple(retired)):
            return True
        async with AsyncExitStack() as retirement:
            async with plan.publication(view, prepared):
                async with window.history_lock:
                    retired = retirement_candidates(contents.children, evidence)
                    if (
                        not is_current()
                        or history is not self.binding.history
                        or not plan.ready(history)
                        or not plan.permits(view, retired)
                    ):
                        return True
                    plan.commit(prepared, page.after)
                    history.publish_committed()
                    retirement.push_async_callback(
                        self.owner.retire_presentations(contents, view.output, retired)
                    )
        if not window.is_attached or not contents.is_attached:
            return True
        if self.native_current():
            self.owner.demand = CLEAN_PUBLICATION
        plan.finish(view, page.after)
        if page.has_newer:
            self.owner.require_commit()
        return True


class ViewBinding:
    """The native view's binding and its view-dependent operations."""

    def matches(self, view: ConversationSessionBinding) -> TypeGuard[Conversation]:
        return False

    def bound_to(self, view: Conversation):
        return view.transcript_binding()

    @property
    def thread_scope(self) -> TranscriptScope:
        return NoTranscript()

    @property
    def coverage(self) -> HistoryCoverage:
        return NO_COVERAGE

    def covers_outgoing(self, message: PublishedSentMessage) -> bool:
        return False

    def covers_input(self, started: InputStartedUpdate) -> bool:
        return False

    def close_source(self) -> None:
        pass

    def replace_source(self):
        return AwaitComplete.nothing()

    @property
    def history(self) -> TranscriptHistory:
        raise ValueError("Saved history requires a bound view")

    def observe_thread(self, owner: TranscriptPresentation) -> None:
        pass

    def capture[FrameT: BoundFrame](
        self, owner: TranscriptPresentation, kind: type[FrameT], *args: ThreadPresentation
    ) -> FrameT | Uncaptured:
        return UNCAPTURED

    def painted(self, owner: TranscriptPresentation, cursor: TranscriptCursor) -> None:
        pass

    def request(self, owner: TranscriptPresentation) -> None:
        """An unbound presentation has nothing to publish."""

    def cancel_workers(self):
        return ()

    def covered(self, owner: TranscriptPresentation, coverage: CoverageEvent, history: CommittedHistory):
        return AwaitComplete.nothing()

    def reset_reader(self) -> None:
        pass

    async def restore_documents(self, owner: TranscriptPresentation) -> None:
        pass

    async def restore(self, owner: TranscriptPresentation) -> None:
        pass


class NoView(ViewBinding):
    """An unbound document has no native work to perform."""


class BoundView(ViewBinding):
    @dataclass(frozen=True)
    class Moment(BoundFrame):
        source: SessionScope

        @classmethod
        def capture(cls, binding: BoundView, owner: TranscriptPresentation, **extra) -> Self:
            return super().capture(
                binding,
                owner,
                source=binding.view.query_ancestor(SessionScope),
                **extra,
            )

        def current(self):
            return (
                super().current()
                and self.source.is_current
                and self.source in self.binding.view.ancestors
            )

    @dataclass(frozen=True)
    class Restoration(Moment):
        revision: int

        def current(self):
            return (
                super().current()
                and not self.owner.closed
                and self.binding.window.scroll_revision == self.revision
            )

        def refresh(self, publication) -> None:
            if not self.current():
                return
            publication.restored(self.owner, self.binding.window)

    def __init__(self, view: Conversation) -> None:
        self.view, self.window, self.contents = view, view.window, view.contents
        self._history, = self.contents.query_children(TranscriptHistory)

    def matches(self, view: ConversationSessionBinding) -> TypeGuard[Conversation]:
        return self.view is view

    def bound_to(self, view: Conversation):
        if not self.matches(view):
            raise ValueError("Transcript already has a native publisher")
        return self

    @property
    def thread_scope(self) -> TranscriptScope:
        view = self.view
        return view.transcript_scope() if view.is_attached else NoTranscript()

    @property
    def reader(self):
        return self.view.app.coordination_access.transcripts

    def current(self):
        return (
            self.view.is_attached
            and not self.view.is_leaving
            and self.window.is_attached
            and self.contents.is_attached
        )

    @property
    def history(self) -> TranscriptHistory:
        return self._history

    def observe_thread(self, owner: TranscriptPresentation) -> None:
        view = self.view
        owner._thread_observation.enter_context(
            self.thread_scope.observe(
                view, view.app.coordination_access, view.thread_observed
            )
        )
        # The shared status may already be published before this view subscribes.
        view.consume_thread_presentation()

    @property
    def coverage(self) -> HistoryCoverage:
        return self.history.state.coverage

    def covers_outgoing(self, message: PublishedSentMessage):
        return self.history.covers_outgoing(message)

    def covers_input(self, started: InputStartedUpdate):
        return self.history.covers_input(started)

    def close_source(self) -> None:
        self.history.close()

    def replace_source(self):
        """Withdraw the old source now; install the identity's reader after joining it."""
        history = self.history
        retirement = history.retire_source()

        async def replace() -> None:
            await retirement
            replacement = TranscriptHistory.empty(
                view=self.view, notification_view=self.contents
            )
            self._history = replacement
            removal = history.remove()
            # Both native membership changes happen before yielding: callbacks
            # see one active reader while the old tree finishes pruning.
            mounted = self.contents.mount(replacement, before=history)
            await mounted
            await removal

        return AwaitComplete(replace())

    async def restore_documents(self, owner: TranscriptPresentation) -> None:
        if not self.view.is_attached or not owner.documents:
            return
        moment = self.Moment.capture(self, owner)
        (source,) = owner.documents
        if not moment.current() or source.closed:
            return
        await self.history.restore_source(source, moment.current)
        if moment.current():
            owner.documents = ()

    async def restore(self, owner: TranscriptPresentation) -> None:
        view = self.view
        view.resume_retained_history()
        if not owner.readable:
            return
        moment = self.Restoration.capture(
            self, owner, revision=view.window.scroll_revision
        )
        position = self.window.reader_position
        history = self.history
        if not await history.restore_reader_ranges(position.ranges, moment.current):
            return
        if not moment.current():
            return
        await self.reveal_retained(owner, history)
        view.refresh_native_projection()
        publication = self.capture(owner, CanonicalSourcePublication)
        view.call_after_refresh(partial(moment.refresh, publication))

    async def reveal_retained(self, owner: TranscriptPresentation, history: TranscriptHistory) -> None:
        view = self.view
        if not view.is_attached:
            return
        self.painted(owner, history.page_source.through)
        view.query_one(SessionDetails)._refresh_summary()

    def capture[FrameT: BoundFrame](
        self, owner: TranscriptPresentation, kind: type[FrameT], *args: ThreadPresentation
    ) -> FrameT | Uncaptured:
        view = self.view
        if not view.is_attached or view.is_leaving:
            return UNCAPTURED
        return kind.capture(self, owner, *args)

    def painted(self, owner: TranscriptPresentation, cursor: TranscriptCursor) -> None:
        frame = BoundFrame.capture(self, owner)
        self.view.call_after_refresh(partial(frame.painted, cursor))

    def request(self, owner) -> None:
        view = self.view
        if not view.is_attached:
            return
        owner.worker = WindowPublicationWork.start(view, partial(owner.published, view, CommitPublication))

    def cancel_workers(self):
        view = self.view
        return (*WindowPublicationWork.cancelled_work(view), *SourcePublicationWork.cancelled_work(view))

    def covered(self, owner: TranscriptPresentation, coverage: CoverageEvent, history: CommittedHistory):
        view = self.view
        contents = self.contents
        if history.is_attached and history.parent is contents:
            owner.events.publish(coverage)
            candidates = retirement_candidates(
                contents.children,
                CommitEvidence(
                    frozenset(),
                    frozenset(coverage.sequences)
                    | history.covered_sequences(
                        frozenset(
                            sequence
                            for child in contents.children
                            for sequence in block_claim(child).required_sequences
                        )
                    ),
                    retained=frozenset({history}),
                    native_inputs=coverage.native_inputs,
                    outgoing=history.outgoing_coverage,
                ),
            )
            protected = protected_blocks(view, candidates)
            retirement = owner.retire_presentations(
                contents,
                view.output,
                [child for child in candidates if child not in protected],
            )

            async def complete() -> None:
                await retirement
                view.query_one(SessionDetails)._refresh_summary()

            return AwaitComplete(complete())
        return AwaitComplete.nothing()

    def reset_reader(self) -> None:
        self.window.reader_position = TailPosition()


class PublicationDemand:
    """What the transcript owes its view: nothing, a refresh, or a commit."""

    pending = False

    def changed(self, cursor: TranscriptCursor) -> PublicationDemand:
        return COMMIT_DEMAND if cursor.requires_commit() else REFRESH_DEMAND

    def commits(self, live_blocks: int, limit: int) -> bool:
        return False


class CleanPublication(PublicationDemand):
    """The view shows everything the transcript holds."""


class RefreshDemand(PublicationDemand):
    """Changed rows await publication; a commit waits for the live-block limit."""

    pending = True

    def commits(self, live_blocks: int, limit: int) -> bool:
        return live_blocks >= limit


class CommitDemand(PublicationDemand):
    """Changed rows must be committed at the next publication."""

    pending = True

    def changed(self, cursor: TranscriptCursor) -> PublicationDemand:
        return self

    def commits(self, live_blocks: int, limit: int) -> bool:
        return True


CLEAN_PUBLICATION = CleanPublication()
REFRESH_DEMAND = RefreshDemand()
COMMIT_DEMAND = CommitDemand()


class TranscriptPresentation:
    """Owns the transcript document; attached native publishers can be replaced."""

    def __init__(self) -> None:
        self.binding: ViewBinding = NoView()
        self.documents: tuple[PreparedPageSource, ...] = ()
        self.closed = False
        self.generation = 0
        self.demand: PublicationDemand = CLEAN_PUBLICATION
        self.displayed_cursor: TranscriptCursor = UnreadTranscriptCursor()
        self.current_read: TranscriptPublicationState = NotPublished()
        self.worker: PublicationWork = NO_PUBLICATION_WORK
        self.source_requests = SourcePublicationRequests(self)
        self._thread_observation = ResourceRelease()
        self.events = CoreEventStream(self)

    def bind(self, view: Conversation) -> ViewBinding:
        if self.closed:
            raise ValueError("Transcript lifetime has ended")
        binding = self.binding.bound_to(view)
        if binding is not self.binding:
            self.invalidate_publications()
            self.current_read = NotPublished()
            self.binding = binding
            self.bind_thread_observation()
        return binding

    def bind_thread_observation(self) -> None:
        """Replace the observation when the owning session changes history source."""
        self._thread_observation.close()
        self.binding.observe_thread(self)

    def _unbind_view(self) -> None:
        self._thread_observation.close()
        self.binding = NoView()

    @property
    def readable(self) -> bool:
        return self.binding.thread_scope.readable

    async def get_transcript_page(
        self, *, position: PagePosition = LatestPage(), limit: PageLimit = AtFrontier(),
    ) -> TranscriptPage:
        frame = self.binding.capture(self, BoundFrame)
        scope = self.binding.thread_scope
        page = await frame.read_page(scope, position=position, limit=limit)
        if self.binding.thread_scope != scope:
            raise ValueError("Thread source changed while reading transcript")
        return page

    @property
    def retained_source_bytes(self) -> int:
        return sum(source.retained_source_bytes for source in self.documents)

    def received(self, page: TranscriptPage) -> None:
        """A read page resumes parked history; a commit adds what the history lacks."""
        history = self.binding.history
        history.state.validate_snapshot(history, page)
        if not history.page_source.contains(page.after):
            self.require_commit()

    @property
    def coverage(self) -> HistoryCoverage:
        return self.binding.coverage

    def covers_outgoing(self, message: PublishedSentMessage) -> bool:
        return self.binding.covers_outgoing(message)

    def covers_input(self, started: InputStartedUpdate) -> bool:
        """Whether saved history already draws the input Core started under this identity.

        A page read can reach the saved input before its start notice reaches
        the conversation. Retirement only removes live blocks that exist when
        a page is accepted, so a start arriving afterwards asks here first.
        """
        return self.binding.covers_input(started)

    def invalidate_publications(self) -> None:
        """Revoke in-flight view work without forgetting its published source."""
        self.generation += 1

    async def published(self, view: Widget, kind: type[TranscriptPublication]) -> None:
        """Run one window publication; once its worker has stopped, publish what it left pending."""
        worker = get_current_worker()
        try:
            await self.publish(kind)
        finally:
            view.call_later(self.window_work_stopped, worker)

    def window_work_stopped(self, worker: Worker) -> None:
        # A superseded worker leaves the retry to the one that replaced it.
        if self.worker.runs(worker):
            self.retry()

    async def publish(self, kind: type[TranscriptPublication], *args: ThreadPresentation) -> bool:
        publication = self.binding.capture(self, kind, *args)
        if publication.current():
            return await publication.publish()
        return True

    def changed(self, cursor: TranscriptCursor) -> None:
        self.invalidate_publications()
        self.demand = self.demand.changed(cursor)
        self.binding.request(self)

    def require_commit(self) -> None:
        self.invalidate_publications()
        self.demand = COMMIT_DEMAND
        self.binding.request(self)

    async def mark_read(
        self, through: TranscriptCursor, acknowledge: Callable[[TranscriptCursor], None], selected: Callable[[], bool]
    ) -> None:
        """A replaced source gets one fresh painted cursor, never a fatal read worker.

        An acknowledgement is in-flight view work: if this source's work was revoked
        while it ran (suspended, retired, closed or changed), the work that replaced it
        paints and acknowledges its own cursor, so a stale one asks for nothing."""
        generation = self.generation
        try:
            await asyncio.to_thread(acknowledge, through)
        except TranscriptChanged:
            if self.generation != generation:
                return
            try:
                fresh = await self.refresh_cursor()
                if selected():
                    await asyncio.to_thread(acknowledge, fresh)
            except TranscriptChanged as error:
                if selected():
                    self.require_commit()
                    self.binding.view.app.show_error(
                        error, "Saved history reloading", severity="warning"
                    )

    async def refresh_cursor(self) -> TranscriptCursor:
        """Commit and return the cursor from the resulting painted transcript."""
        self.require_commit()
        frame = self.binding.capture(self, BoundFrame)
        # A frame stops being current only for good: one that is not now never publishes.
        if not frame.current():
            raise TranscriptChanged()
        await self.worker.settled()
        if not frame.current():
            raise TranscriptChanged()
        ready = asyncio.get_running_loop().create_future()
        frame.after_refresh(lambda: ready.set_result(self.displayed_cursor))
        cursor = await ready
        if cursor.requires_commit():
            raise TranscriptChanged()
        return cursor

    def retry(self) -> None:
        if self.source_requests.resume():
            return
        if not self.demand.pending or not self.worker.is_finished:
            return
        if self.binding.capture(self, CommitPublication).ready_to_commit():
            self.binding.request(self)

    def source_work_finished(self, view: Conversation) -> None:
        if self.binding.matches(view):
            self.retry()

    async def close(self) -> None:
        self.closed = True
        try:
            async with AsyncResourceRelease() as release:
                release.callback(self.binding.close_source)
                release.callback(self._close_documents)
                await self.suspend()
        finally:
            self._unbind_view()
            self.displayed_cursor = UnreadTranscriptCursor()

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
        work, self.worker = self.worker, NO_PUBLICATION_WORK
        for joined in (work, self.source_requests.cancel(), *self.binding.cancel_workers()):
            await joined.joined()

    def retire_presentations(
        self, contents: Contents, output: LiveOutput, candidates: Sequence[Widget]
    ) -> AwaitComplete:
        """Withdraw covered native paint now; join teardown outside source locks.

        CommitEvidence has already selected these exact resources. Their native
        display lifetime ends synchronously, so accepted saved rows cannot paint
        alongside them while an original stream finishes its paged publication.
        The separate teardown task handles cancellation; source transactions
        register its completion outside their mutation locks.
        """
        if not candidates:
            return AwaitComplete.nothing()

        if any(candidate.display for candidate in candidates):
            # Their rows leave the window now; the reader stays on theirs.
            contents.query_ancestor(HistoryWindow).keep_reader()
        for candidate in candidates:
            candidate.display = False
        retirement = asyncio.create_task(
            self._retire_presentations(contents, output, candidates),
            name="accepted source retirement",
        )
        return AwaitComplete(join_retirement(retirement))

    async def _retire_presentations(self, contents: Contents, output: LiveOutput, candidates: Sequence[Widget]) -> None:
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
                self._thread_observation.close()
                self.source_requests.cancel()
                self.invalidate_publications()
                self.current_read = NotPublished()
                self._close_documents()
                self.demand = CLEAN_PUBLICATION
                self.displayed_cursor = UnreadTranscriptCursor()
                work, self.worker = self.worker, NO_PUBLICATION_WORK
                work.cancel()
                # A different origin does not authorize reusing these pages.
                # Withdraw every old source before joining any cancelled work.
                replacement = self.binding.replace_source()
                self.binding.reset_reader()
                await replacement
                self.bind_thread_observation()

    async def detach(self, view: Conversation) -> None:
        if not self.binding.matches(view):
            return
        self._thread_observation.close()
        await self.suspend()
        if self.closed or not self.binding.matches(view):
            return
        generation = self.generation
        history = self.binding.history
        documents = await history._source_state.retirement_source().coverage.retire(history)
        if self.closed or not self.binding.matches(view) or self.generation != generation:
            for source in documents:
                source.close()
            return
        self._close_documents()
        self.documents = documents
        self._unbind_view()
        self.displayed_cursor = UnreadTranscriptCursor()
