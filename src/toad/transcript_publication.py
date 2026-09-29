"""Source-fenced saved transcript publication; checkpoint policy stays declared."""
from __future__ import annotations

import weakref
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from textual.worker import Worker, WorkerCancelled

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation, Window, Contents


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
        from toad.widgets.transcript_fragments import prepare_transcript_fragments
        from toad.widgets.transcript_history import TranscriptHistory
        from toad.widgets.session_details import SessionDetails
        fragments = await prepare_transcript_fragments(self.page.events, self.owner.view.app.render_processes)
        if not self.current() or self.agent is None:
            return
        view = self.owner.view
        history = TranscriptHistory(self.page, self.agent.get_transcript_page, fragments=fragments)
        view.output.boundary()
        if self.window.scroll_revision == self.scroll_revision:
            self.window.anchor()
        with view.app.batch_update():
            await self.contents.mount(history)
        if not self.current():
            if history.is_attached:
                await history.remove()
            return
        view.query_one(SessionDetails)._refresh_summary()
        self.owner.painted(self.page.after)


class CheckpointPublication(TranscriptPublication):
    def __init__(self, owner, view, window, contents):
        from toad.widgets.committed_presentation import checkpoint_plan
        super().__init__(owner, view, window, contents)
        self.plan = checkpoint_plan(window)

    def current(self) -> bool:
        view = self.owner.view
        return (super().current() and not view._pruning
                and view.turns.managed_id is None and self.plan.current(self.window))

    async def publish(self) -> None:
        from agent_comms.errors import UnregisteredThreadError

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
            or view.turns.managed_id is not None
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
        except UnregisteredThreadError:
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
            frozenset(before_read), prepared.sequences, prepared.history
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

    @property
    def view(self) -> Conversation | None:
        return self._view()

    def invalidate(self) -> None:
        self.generation += 1

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
        frontier = self.displayed_cursor
        if frontier is not None and frontier.session_file == page.after.session_file:
            if frontier.offset < page.after.offset:
                # The existing evidence/viewport policy advances retained content;
                # a load response is not a reason to append its whole page twice.
                self.require_checkpoint()
            return
        self.invalidate()
        await self.publish(SnapshotPublication, page)

    def painted(self, cursor: TranscriptCursor) -> None:
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
        view.call_after_refresh(record)

    def source_changed(self) -> None:
        self.invalidate()
        self.dirty = self.checkpoint_required = False
        self.displayed_cursor = None
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
        self.worker = view.run_worker(self.publish(CheckpointPublication),
                                      group="transcript-window", exclusive=True)
        return self.worker

    def retry(self) -> None:
        if self.dirty:
            self.request()

    async def close(self) -> None:
        self.invalidate()
        self._view = lambda: None
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.cancel()
            try:
                await worker.wait()
            except WorkerCancelled:
                pass

    async def covered(self, message) -> None:
        from toad.widgets.conversation import Contents
        from toad.widgets.committed_presentation import (
            CommitEvidence,
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
                    frozenset(message.sequences),
                    message.history,
                ),
            )
            protected = protected_blocks(view, candidates)
            await contents.remove_children(
                [child for child in candidates if child not in protected]
            )

