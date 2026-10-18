"""Conversation comms behavior on the existing receiver MRO."""

from __future__ import annotations
from toad.core_event_carrier import CoreEventReceiver
from toad.core_event_carrier import CoreEventMessage
import agent_comms.agent_events as comms_events
from agent_comms.acp_extension import CompactionChangedUpdate, CoordinationChangedUpdate, GoalChangedUpdate, InputFailedUpdate, InputStartedUpdate, PromptCancelledUpdate, McpClientAcknowledgementUpdate, TranscriptChangedUpdate, TranscriptSnapshotUpdate, TurnChangedUpdate
from agent_comms.mro_dispatch import handles
from textual.content import Content
from toad.core import events as core_events
from toad.acp.attachment_presentation import CursorPresentation, QueuePresentation
from toad.widgets.note import Note
from toad.widgets.markdown_note import MarkdownNote


class ConversationCommsHandlers(CoreEventReceiver):
    @handles(CursorPresentation)
    def on_private_native_cursor_update(
        self, update: CursorPresentation, message: CoreEventMessage
    ) -> None:
        message.stop()
        if (
            message.publisher is not self.agent
            or self.agent is None
            or message.event.session_id != self.agent.session_id
            or message.event.sequence <= self._private_cursor_sequence
        ):
            return
        self._private_cursor_sequence = message.event.sequence
        self.native_history_status = update.status

    @handles(McpClientAcknowledgementUpdate)
    async def on_mcp_client_status(
        self, update: McpClientAcknowledgementUpdate, message: CoreEventMessage
    ) -> None:
        """Show the MCP server summary only within the active turn it describes."""
        # The message carries the validated turn identity; a delayed or queued
        # message from an older agent cannot attach to a successor turn here.
        agent_session = self.agent.session_id if self.agent else None
        if (
            message.publisher is not self.agent
            or (self.agent.current_turn.managed_id if self.agent else None)
            != update.turn_id
            or self.turns.managed_id is None
            or update.turn_id != self.turns.managed_id
            or (agent_session is not None and message.event.session_id != agent_session)
        ):
            # Late or forged: the projection dies with its turn and is never
            # shown outside the active-turn lifetime.
            return
        if self._mcp_live_note is not None:
            return  # The package emits at most one server summary per turn.
        rows = update.acknowledgement.servers
        summary = (
            "; ".join(
                f"{row.id}[{row.scope}] {row.state.declared_name} calls={row.calls.declared_name}"
                f" tools={row.tools} resources={row.resources} prompts={row.prompts}"
                for row in rows
            )
            or "no approved servers"
        )
        self.output.boundary()
        self._mcp_live_note = Note(
            Content.styled(
                f"MCP live (this turn, not a grant): {summary}", "$text-muted"
            ),
        )
        await self.post(self._mcp_live_note)

    @handles(TurnChangedUpdate)
    async def on_turn_changed(
        self, update: TurnChangedUpdate, message: CoreEventMessage
    ) -> None:
        if not self.turns.changed(message):
            return
        self.app.events.publish(core_events.OpenTabsChanged())
        if self.turns.owner.busy:
            self.transcript.invalidate_publications()
            return
        await self._clear_mcp_live()
        self._agent_activity_boundary.reset()
        await self.output.settle()
        self.transcript.retry()

    @handles(QueuePresentation)
    async def on_queue_view_update(
        self, update: QueuePresentation, message: CoreEventMessage
    ) -> None:
        if (
            self.agent is None
            or message.publisher is not self.agent
            or message.event.session_id != self.agent.session_id
        ):
            return
        async with self.window.preserve_history(root=self.contents):
            for started in update.starts:
                if (
                    message.publisher is not self.agent
                    or message.event.session_id != self.agent.session_id
                ):
                    return
                await self.present_started_input(started)
            self.submissions.publish_pending()

    @handles(InputStartedUpdate)
    async def on_input_started(
        self, update: InputStartedUpdate, message: CoreEventMessage
    ) -> None:
        if (
            self.agent is None
            or message.publisher is not self.agent
            or message.event.session_id != self.agent.session_id
        ):
            return
        if update.text is not None:
            async with self.window.preserve_history(root=self.contents):
                await self.present_started_input(update)
                self.submissions.publish_pending()

    @handles(InputFailedUpdate)
    def on_input_failed(
        self, update: InputFailedUpdate, message: CoreEventMessage
    ) -> None:
        """Only a locally failed request may recover its own draft text."""
        if not self.submissions.accepts_failure(message):
            return
        if not message.event.recover_draft:
            # Server notices (including unstarted queued/restored inputs) are
            # read-only evidence, not permission to change the local composer.
            self.flash(
                f"{message.event.update.failure.title}: {message.event.update.failure.description}\n{message.event.update.failure.input_disposition}\n{message.event.update.failure.action}",
                style="error",
            )
            return
        self.submissions.restore_draft(message.event.update.text)

        self.flash(
            f"{message.event.update.failure.title}; draft restored: {message.event.update.failure.description}\n{message.event.update.failure.input_disposition}\n{message.event.update.failure.action}",
            style="error",
        )

    @handles(core_events.CommsUpdated)
    async def on_comms_updated(self, event: CoreEventMessage) -> None:
        if (event.publisher is not self.agent
                or event.event.session_id != self.agent.session_id):
            event.stop()
            return
        await self.dispatch(event.event.update, event)

    @handles(CoordinationChangedUpdate)
    def on_coordination_changed(
        self, update: CoordinationChangedUpdate, message: CoreEventMessage
    ) -> None:
        # Source binding is published independently of registry/activity changes:
        # a newly bound thread joins the observed threads (or reads as foreign).
        self.arm_thread_read()
        self.refresh_thread_status()
        self.prompt.sync_session()
        self.prompt.sync_queue()

    @handles(PromptCancelledUpdate)
    async def on_prompt_cancelled(
        self, update: PromptCancelledUpdate, message: CoreEventMessage
    ) -> None:
        await self.post(MarkdownNote(
            f"## Turn cancelled\n\n{update.feedback}", classes="-stop-reason"))

    @handles(TranscriptChangedUpdate)
    def on_transcript_changed(
        self, update: TranscriptChangedUpdate, message: CoreEventMessage
    ) -> None:
        self.transcript.changed(update.cursor)

    @handles(GoalChangedUpdate)
    def on_goal_changed(
        self, update: GoalChangedUpdate, message: CoreEventMessage
    ) -> None:
        self.goal_observation.receive(message.publisher, update)

    @handles(CompactionChangedUpdate)
    async def on_compaction_changed(
        self, update: CompactionChangedUpdate, message: CoreEventMessage
    ) -> None:
        await self.dispatch(update.event, message)

    @handles(comms_events.CompactionEnd)
    def on_compaction_end(self, event: comms_events.CompactionEnd,
                          message: CoreEventMessage) -> None:
        # Pi's saved compaction entry owns the notice; re-read the transcript.
        self.transcript.require_commit()

    @handles(TranscriptSnapshotUpdate)
    def on_transcript_snapshot(
        self, update: TranscriptSnapshotUpdate, message: CoreEventMessage
    ) -> None:
        self.transcript.received(update.page)
