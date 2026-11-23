"""Toolkit-neutral conversation comms handlers shared by Textual and Qt."""

from __future__ import annotations

from abc import abstractmethod

import agent_comms.agent_events as comms_events
from agent_comms.acp_extension import (
    CompactionChangedUpdate,
    CoordinationChangedUpdate,
    GoalChangedUpdate,
    InputFailedUpdate,
    InputStartedUpdate,
    NativeRoundCommittedUpdate,
    PromptCancelledUpdate,
    TranscriptChangedUpdate,
    TranscriptSnapshotUpdate,
    TurnChangedUpdate,
)
from metaclass_registry.mro_dispatch import handles

from toad.acp.attachment_presentation import QueuePresentation
from toad.client.subscribers import CoreObserverDispatch
from toad.core import events as core_events
from toad.core.events import Publication


class ConversationCommsHandlers(CoreObserverDispatch):
    """Handles Core `CommsUpdated` events and session-scoped update filtering for every
    frontend's conversation view. Each frontend supplies only its presentation hooks."""

    def accepts(self, message: Publication) -> bool:
        if not message.event.session_scoped:
            return True
        if not self.agent_binding.accepts_message(message):
            return False
        return self.turns.owner.accepts_update(message.event.update)

    async def turn_settled(self) -> None:
        """Frontend cleanup when an observed turn finishes (Textual clears its MCP live note)."""

    def goal_changed_from(self, publisher: object) -> None:
        """Invalidate this view's goal observation if it owns one."""

    @abstractmethod
    async def present_started_user_input(self, started: InputStartedUpdate) -> None:
        """Draw a started native user input carrying its `StartedInputClaim`."""

    @abstractmethod
    def restore_composer_draft(self, text: str) -> None:
        """Return failed-request draft text to this view's composer."""

    @abstractmethod
    def coordination_synced(self) -> None:
        """Refresh composer session/queue chrome after coordination changes."""

    @abstractmethod
    async def present_turn_cancelled(self, feedback: str) -> None:
        """Show the cancelled-turn notice in this view."""

    async def present_started_input(self, started: InputStartedUpdate) -> None:
        self.output.boundary()
        if started.text and not self.transcript.binding.covers_input(started):
            await self.present_started_user_input(started)
        self.submissions.native_input_presented(started)

    @handles(TurnChangedUpdate)
    async def on_turn_changed(
        self, update: TurnChangedUpdate, message: Publication
    ) -> None:
        if not self.turns.changed(message):
            return
        if self.turns.owner.busy:
            return
        await self.turn_settled()
        await self.output.settle()
        self.transcript.retry()

    @handles(QueuePresentation)
    async def on_queue_view_update(
        self, update: QueuePresentation, message: Publication
    ) -> None:
        async with self.window.preserve_history():
            for started in update.starts:
                await self.present_started_input(started)
            self.submissions.publish_pending()

    @handles(InputStartedUpdate)
    async def on_input_started(
        self, update: InputStartedUpdate, message: Publication
    ) -> None:
        async with self.window.preserve_history():
            await self.present_started_input(update)
            self.submissions.publish_pending()

    @handles(InputFailedUpdate)
    def on_input_failed(
        self, update: InputFailedUpdate, message: Publication
    ) -> None:
        """Only a locally failed request may recover its own draft text."""
        if not self.submissions.accepts_failure(message):
            return
        failure = message.event.update.failure
        if not message.event.recover_draft:
            # Server notices (including unstarted queued/restored inputs) are
            # read-only evidence, not permission to change the local composer.
            self.flash_error(
                f"{failure.title}: {failure.description}\n{failure.input_disposition}\n{failure.action}"
            )
            return
        self.restore_composer_draft(message.event.update.text)
        self.flash_error(
            f"{failure.title}; draft restored: {failure.description}\n{failure.input_disposition}\n{failure.action}"
        )

    @handles(core_events.CommsUpdated)
    async def on_comms_updated(self, event: core_events.CommsUpdated, message: Publication) -> None:
        await self.dispatch(event.update, message)

    @handles(CoordinationChangedUpdate)
    def on_coordination_changed(
        self, update: CoordinationChangedUpdate, message: Publication
    ) -> None:
        # Source binding is published independently of registry/activity changes:
        # a newly bound thread joins the observed threads (or reads as foreign).
        self.arm_thread_read()
        self.refresh_thread_status()
        self.coordination_synced()

    @handles(PromptCancelledUpdate)
    async def on_prompt_cancelled(
        self, update: PromptCancelledUpdate, message: Publication
    ) -> None:
        await self.present_turn_cancelled(update.feedback)

    @handles(TranscriptChangedUpdate)
    def on_transcript_changed(
        self, update: TranscriptChangedUpdate, message: Publication
    ) -> None:
        self.transcript.changed(update.cursor)

    @handles(NativeRoundCommittedUpdate)
    def on_native_round_committed(
        self, update: NativeRoundCommittedUpdate, message: Publication
    ) -> None:
        self.transcript.require_commit()

    @handles(GoalChangedUpdate)
    def on_goal_changed(
        self, update: GoalChangedUpdate, message: Publication
    ) -> None:
        self.goal_changed_from(message.publisher)

    @handles(CompactionChangedUpdate)
    async def on_compaction_changed(
        self, update: CompactionChangedUpdate, message: Publication
    ) -> None:
        await self.dispatch(update.event, message)

    @handles(comms_events.CompactionEnd)
    def on_compaction_end(
        self, event: comms_events.CompactionEnd, message: Publication
    ) -> None:
        # Pi's saved compaction entry owns the notice; re-read the transcript.
        self.transcript.require_commit()

    @handles(TranscriptSnapshotUpdate)
    def on_transcript_snapshot(
        self, update: TranscriptSnapshotUpdate, message: Publication
    ) -> None:
        self.transcript.received(update.page)
