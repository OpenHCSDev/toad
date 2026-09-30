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

    @abstractmethod
    async def publish(self) -> None: ...


class SnapshotPublication(TranscriptPublication):
    def __init__(self, owner, view, window, contents, page: TranscriptPage):
        super().__init__(owner, view, window, contents)
        self.page = page
        self.scroll_revision = window.scroll_revision

    async def publish(self) -> None:
        from toad.render_tasks import TranscriptRenderTask
        from toad.work_preparation import RenderPreparation
        from toad.widgets.transcript_history import TranscriptHistory
        from toad.widgets.session_details import SessionDetails
        from toad.widgets.committed_presentation import CommitEvidence, retirement_candidates
        fragments = await self.owner.view.app.preparation.submit(
            RenderPreparation(TranscriptRenderTask(self.page.events))
        )
        if not self.current() or self.agent is None:
            return
        view = self.owner.view
        history = TranscriptHistory(self.page, self.agent.get_transcript_page, fragments=fragments)
        self.owner.prepare_reader(history)
        view.output.boundary()
        with view.app.batch_update():
            await self.contents.mount(history)
            if self.current():
                # Initial/rebound saved source owns the same retirement relation
                # as later checkpoints. Captured anonymous live output has no
                # proof here; original native input IDs do.
                evidence = CommitEvidence(
                    frozenset(), retained_history=history,
                    native_inputs=frozenset(native_id for event in self.page.events
                                            for native_id in event.native_inputs),
                )
                await self.contents.remove_children(retirement_candidates(self.contents.children, evidence))
        if not self.current():
            if history.is_attached:
                await history.remove()
            return
        view.query_one(SessionDetails)._refresh_summary()
        self.owner.painted(self.page.after, reader_revision=self.scroll_revision)


class HandlingPublication(TranscriptPublication):
    """Render original recipient outcomes on existing original source bodies."""

    async def publish(self) -> None:
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

    async def publish(self) -> None:
        if self.agent is None or not self.agent.transcript_ready:
            return
        page = await self.agent.get_transcript_page()
        if self.current():
            await self.owner.snapshot(page)
            await self.owner.publish(HandlingPublication)


class ObservedSourcePublication(CanonicalSourcePublication):
    def __init__(self, owner, view, window, contents, presentation):
        super().__init__(owner, view, window, contents)
        self.presentation = presentation

    async def publish(self) -> None:
        if self.agent is None:
            return
        await self.agent.observe_thread_presentation(self.presentation)
        if self.current():
            await super().publish()


class SourcePublicationRequests:
    """One running read and one coalesced original request, never model state."""

    def __init__(self, owner: TranscriptPresentation):
        self.owner = owner
        self.pending: asyncio.Queue[tuple[type[TranscriptPublication], tuple[object, ...]]] = asyncio.Queue(maxsize=1)
        self.worker: Worker[None] | None = None

    def request(self, kind: type[TranscriptPublication], *args: object) -> None:
        view = self.owner.view
        if view is None or not view.is_attached:
            return
        if self.pending.full():
            self.pending.get_nowait()
        self.pending.put_nowait((kind, args))
        if self.worker is None or self.worker.is_finished:
            self.worker = view.run_worker(self.publish, group="transcript-source")

    async def publish(self) -> None:
        from agent_comms.coordination_errors import StaleRevision

        while not self.pending.empty():
            kind, args = self.pending.get_nowait()
            try:
                await self.owner.publish(kind, *args)
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

    async def publish(self) -> None:
        from agent_comms.errors import UnregisteredThreadError
        from agent_comms.coordination_errors import StaleRevision

        from toad.acp.agent import Agent
        from toad.widgets.committed_presentation import (
            CheckpointBarrier,
            CommitEvidence,
            CommitParticipant,
            CommittedHistory,
            retirement_candidates,
        )
        from toad.widgets.transcript_history import TranscriptHistory

        view = self.owner.view
        if view is None:
            return
        window, contents = self.window, self.contents
        if (
            window is None
            or contents is None
            or not self.owner.dirty
            or not isinstance(view.agent, Agent)
            or not view.agent_ready
            or not view.agent.transcript_ready
            or any(
                isinstance(node, CheckpointBarrier) for node in contents.walk_children()
            )
            or (
                not self.owner.checkpoint_required
                and len(contents.children) < view.MAX_LIVE_BLOCKS
            )
        ):
            return
        agent, plan = self.agent, self.plan
        # A page cannot replace live blocks posted while its read or fragment
        # preparation is in flight unless it explicitly contains their identity.
        before_read = tuple(contents.children)
        history = next(
            (child for child in before_read if isinstance(child, CommittedHistory)),
            None,
        )
        potential = tuple(
            child
            for child in before_read
            if child is not history and isinstance(child, CommitParticipant)
        )
        if not plan.ready(history) or not plan.permits(view, potential):
            return

        is_current = self.current

        try:
            page = await agent.get_transcript_page()
            if not page.events or not is_current():
                return
            prepared = await plan.prepare(view, history, page, before_read, is_current)
        except (UnregisteredThreadError, StaleRevision):
            # Deletion can retire the model before the attachment's final
            # transcript notification has drained. Its view is closing too.
            return
        except (OSError, ValueError) as error:
            if is_current():
                view.notify(str(error), title="Committed history", severity="error")
            return
        if prepared is None or not is_current():
            return
        evidence = CommitEvidence(
            view.turns.owner.captured_snapshot(before_read), prepared.sequences, prepared.history,
            frozenset(native_id for event in page.events for native_id in event.native_inputs),
        )
        async with window.history_lock:
            retired = retirement_candidates(contents.children, evidence)
            if (
                not is_current()
                or not plan.ready(prepared.history)
                or not plan.permits(view, retired)
            ):
                return
            view.output.boundary()
            if view.cursor_block in retired:
                view.cursor.follow(None)
            async with plan.publication(view, prepared):
                replacement = None
                accepted = False
                try:
                    if prepared.history is None:
                        replacement = TranscriptHistory(
                            page,
                            agent.get_transcript_page,
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
                    await contents.remove_children(retired)
                finally:
                    if (
                        not accepted
                        and replacement is not None
                        and replacement.is_attached
                    ):
                        await replacement.remove()
        if not window.is_attached or not contents.is_attached:
            return
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
        self._revealed_history: TranscriptHistory | None = None
        self.source_requests = SourcePublicationRequests(self)

    @property
    def view(self) -> Conversation | None:
        return self._view()

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
        from toad.widgets.transcript_history import TranscriptHistory

        view = self.view
        history = next((child for child in view.contents.children
                        if isinstance(child, TranscriptHistory)), None)
        if history is None:
            await view.present_retained_native_session()
            return
        source = view.query_ancestor(SessionView)
        await self.reveal_retained(history)
        await view.refresh_native_projection()

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
        self._revealed_history = history
        self.displayed_cursor = history.committed_cursor
        self.reader_position = None
        if (loading := view.query_one_optional(ThreadLoading)) is not None:
            await loading.remove()
        view.remove_class("-initial-loading")
        view.query_one(SessionDetails)._refresh_summary()

    async def refresh_revealed(self, agent) -> None:
        """Validate the retained reader after its first completed display."""
        from toad.transcript_state import ParkedSourceTranscript
        from toad.widgets.transcript_history import TranscriptHistory

        generation = self.generation
        page = await agent.get_transcript_page()
        view = self.view
        if (view is None or view.agent is not agent or generation != self.generation
                or not view.is_attached):
            return
        history = self._revealed_history
        if history is None or not history.is_attached:
            await self.snapshot(page)
            return
        latest = history.pages[-1].page
        if (page.after.session_file == history.through.session_file
                and page.after.offset >= history.through.offset
                and (page.after.offset > history.through.offset or page.events == latest.events)):
            for node in history.walk_children(with_self=True):
                if (isinstance(node, TranscriptHistory)
                        and isinstance(node._source_state, ParkedSourceTranscript)):
                    node.resume_source()
            self._revealed_history = None
            await self.snapshot(page)
        else:
            self._revealed_history = None
            await history.remove()
            self.displayed_cursor = None
            self.invalidate()
            await self.publish(SnapshotPublication, page)

    async def publish(self, kind: type[TranscriptPublication], *args) -> None:
        from toad.widgets.conversation import Window, Contents
        view = self.view
        if view is None or not view.is_attached:
            return
        window, contents = view.query_one_optional(Window), view.query_one_optional(Contents)
        if window is None or contents is None:
            return
        publication = kind(self, view, window, contents, *args)
        if publication.current():
            await publication.publish()

    async def snapshot(self, page: TranscriptPage) -> None:
        from toad.widgets.conversation import Window
        view = self.view
        window = view.query_one_optional(Window) if view is not None else None
        frontiers = [history.committed_cursor for history in window.histories
                     if history.is_attached and history.state.reports_coverage] if window is not None else []
        if self.displayed_cursor is not None:
            frontiers.append(self.displayed_cursor)
        frontier = max((cursor for cursor in frontiers
                        if cursor.session_file == page.after.session_file),
                       key=lambda cursor: (cursor.offset, cursor.wire_seq), default=None)
        if frontier is not None:
            if not frontier.contains(page.after):
                # The existing evidence/viewport policy advances retained content;
                # a load response is not a reason to append its whole page twice.
                self.require_checkpoint()
            return
        self.invalidate()
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
        self._revealed_history = None
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
        if self.dirty:
            self.request()

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
            await contents.remove_children(
                [child for child in candidates if child not in protected]
            )
