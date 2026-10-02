"""Consume declared Comms facts through the shared nominal dispatcher."""

from __future__ import annotations

import os

from agent_comms.acp_extension import (
    CompactionChangedUpdate,
    CompactionCommittedUpdate,
    CompactionPublishedUpdate,
    CoordinationChangedUpdate,
    CursorAdvancedUpdate,
    GoalChangedUpdate,
    InputDeliveryChangedUpdate,
    InputFailedUpdate,
    InputStartedUpdate,
    PromptCancelledUpdate,
    McpClientReceiptUpdate,
    QueueChangedUpdate,
    RequestFailedUpdate,
    SelectedWriteAcceptedUpdate,
    TextRouteUpdate,
    TranscriptChangedUpdate,
    TranscriptSnapshotUpdate,
    TurnChangedUpdate,
)
from agent_comms.mro_dispatch import MroDispatch, handles
from toad.conversation_turn import OrderedManagedTurn, ManagedTurn

from . import messages


class CommsUpdateConsumer(MroDispatch):
    turn_class = OrderedManagedTurn
    def __init__(
        self,
        agent,
        session_id: str,
        *,
        cursor_token: int | None = None,
        queue_token: int | None = None,
        turn_token: int | None = None,
    ):
        self.agent = agent
        self.session_id = session_id
        self.route = None
        self.compaction_receipt = None
        self.cursor_token = cursor_token
        self.queue_token = queue_token
        self.turn_token = turn_token

    def accepts_turn(self):
        return (self.agent.process.accepts_session(self.session_id)
                and (self.turn_token is None or (
                    self.turn_token == self.agent.presentation.turns.sequence
                    # A snapshot response can observe native completion before
                    # the ordered ACP stream delivers its remaining chunks.
                    # Only ordered lifecycle notifications settle that turn.
                    and self.agent.current_turn.accepts_snapshot
                )))

    def require_compaction_receipt(self):
        if self.compaction_receipt is None:
            raise ValueError('Compaction result was missing')
        return self.compaction_receipt

    @handles(TextRouteUpdate)
    def text_route(self, update: TextRouteUpdate) -> None:
        self.route = update.route

    @handles(InputFailedUpdate)
    def input_failed(self, update: InputFailedUpdate) -> None:
        self.agent.post_message(
            messages.CommsUpdated(
                update,
                recover_draft=False,
                agent=self.agent,
                session_id=self.session_id,
            )
        )

    @handles(TranscriptChangedUpdate)
    def transcript_changed(self, update: TranscriptChangedUpdate) -> None:
        self.agent.post_message(
            messages.CommsUpdated(update, self.agent, self.session_id)
        )

    @handles(TurnChangedUpdate)
    def turn_changed(self, update: TurnChangedUpdate) -> None:
        if not self.accepts_turn():
            return
        agent = self.agent
        binding = agent.presentation.managed_turns()
        if not binding.receive(update.state, self.turn_class):
            return
        agent.post_message(messages.CommsUpdated(
            update, agent=agent, session_id=self.session_id, sequence=binding.sequence))

    @handles(CursorAdvancedUpdate)
    def cursor_advanced(self, update: CursorAdvancedUpdate) -> None:
        if self.cursor_token is None:
            self.agent._private_cursor.callback(update.envelope, self.session_id)
        else:
            self.agent._private_cursor.bind(
                update.envelope, self.session_id, self.cursor_token
            )
        self.agent._post_private_cursor()

    @handles(QueueChangedUpdate)
    def queue_changed(self, update: QueueChangedUpdate) -> None:
        if self.queue_token is None:
            self.agent.queue_attachment.callback(update, self.session_id)
            starts = ()
        else:
            _, starts = self.agent.queue_attachment.bind(
                update, self.session_id, self.queue_token
            )
        self.agent._post_queue_view(starts)

    @handles(InputStartedUpdate)
    def input_started(self, update: InputStartedUpdate) -> None:
        if update.scope is None:
            if update.input_id is None and self.session_id == self.agent.session_id:
                self.agent.post_message(
                    messages.CommsUpdated(
                        update, agent=self.agent, session_id=self.session_id
                    )
                )
            return
        starts = self.agent.queue_attachment.started(update, self.session_id)
        self.agent._post_queue_view(starts)

    @handles(CoordinationChangedUpdate)
    def coordination_changed(self, update: CoordinationChangedUpdate) -> None:
        from dataclasses import replace
        from pathlib import Path

        from .context_measurement import ContextMeasurement
        from .maintenance_ingress import configured_root

        agent = self.agent
        attached_env = (agent.process.env or os.environ).copy()
        attached_env["AGENT_COMMS_ROOT"] = update.wire_root
        root = configured_root(
            attached_env, agent.process.cwd or agent.project_root_path.resolve()
        )
        agent.coordination = replace(update, wire_root=str(root))
        agent.project_root_path = Path(update.worktree)
        agent.context_measurement = ContextMeasurement.saved(update.context_usage)
        agent.update_status_line()
        agent.post_message(
            messages.CommsUpdated(agent.coordination, agent, self.session_id)
        )
        agent.session.coordinated_title(update.title)

    @handles(GoalChangedUpdate)
    def goal_changed(self, update: GoalChangedUpdate) -> None:
        self.agent.post_message(
            messages.CommsUpdated(update, self.agent, self.session_id)
        )

    @handles(CompactionChangedUpdate)
    def compaction_changed(self, update: CompactionChangedUpdate) -> None:
        from .context_measurement import ContextUnavailable
        self.agent.context_measurement = ContextUnavailable("Native context measurement is pending")
        self.agent.update_status_line()
        self.agent.post_message(
            messages.CommsUpdated(update, self.agent, self.session_id)
        )

    @handles(CompactionCommittedUpdate)
    def compaction_committed(self, update: CompactionCommittedUpdate) -> None:
        self.compaction_receipt = update

    @handles(TranscriptSnapshotUpdate)
    def transcript_snapshot(self, update: TranscriptSnapshotUpdate) -> None:
        controller = self.agent.controller
        controller.start_operation(controller.publish_transcript_snapshot(
            update, controller.surface, controller.session))

    @handles(InputDeliveryChangedUpdate)
    def input_delivery_changed(self, update: InputDeliveryChangedUpdate) -> None:
        from toad.core.events import InputDispositionsChanged
        self.agent.events.publish(InputDispositionsChanged())

    @handles(CompactionPublishedUpdate)
    def compaction_published(self, update: CompactionPublishedUpdate) -> None:
        self.agent.post_message(
            messages.CommsUpdated(update, self.agent, self.session_id)
        )

    @handles(McpClientReceiptUpdate)
    def mcp_receipt(self, update: McpClientReceiptUpdate) -> None:
        if (
            self.session_id != self.agent.session_id
            or update.turn_id != self.agent.current_turn.managed_id
        ):
            self.agent.log(
                "[ACP MCP live receipt rejected] receipt is not bound to the active session/turn"
            )
            return
        self.agent.post_message(
            messages.CommsUpdated(update, self.agent, self.session_id)
        )

    @handles(SelectedWriteAcceptedUpdate)
    def selected_write_accepted(self, update):
        pass

    @handles(RequestFailedUpdate)
    def request_failed(self, update):
        from toad.agent import LogAgentFail

        failure = update.failure
        self.agent.post_message(
            LogAgentFail(failure.title, failure.feedback, log_path=self.agent.presentation.log_path)
        )

    @handles(PromptCancelledUpdate)
    def prompt_cancelled(self, update):
        self.agent.post_message(messages.CommsUpdated(update, self.agent, self.session_id))


class OwnerSnapshotConsumer(CommsUpdateConsumer):
    """Snapshot turns reconcile controls without overtaking ordered output."""
    turn_class = ManagedTurn
