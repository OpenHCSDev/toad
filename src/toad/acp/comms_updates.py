"""Consume declared Comms facts through the shared nominal dispatcher."""

from __future__ import annotations

from agent_comms.acp_extension import (
    TranscriptSnapshotUpdate,
    InputDeliveryChangedUpdate,
    CompactionPublishedUpdate,
    McpClientReceiptUpdate,
    CompactionChangedUpdate,
    CompactionCommittedUpdate,
    CoordinationChangedUpdate,
    GoalChangedUpdate,
    CursorAdvancedUpdate,
    InputFailedUpdate,
    InputStartedUpdate,
    QueueChangedUpdate,
    TextRouteUpdate,
    TranscriptChangedUpdate,
    TurnSettledUpdate,
    TurnStartedUpdate,
)
from agent_comms.mro_dispatch import MroDispatch, handles

from . import messages


class CommsUpdateConsumer(MroDispatch):
    def __init__(
        self,
        agent,
        session_id: str,
        *,
        cursor_token: int | None = None,
        queue_token: int | None = None,
    ):
        self.agent = agent
        self.session_id = session_id
        self.route = None
        self.compaction_receipt = None
        self.cursor_token = cursor_token
        self.queue_token = queue_token

    @handles(TextRouteUpdate)
    def text_route(self, update: TextRouteUpdate) -> None:
        self.route = update.route

    @handles(InputFailedUpdate)
    def input_failed(self, update: InputFailedUpdate) -> None:
        self.agent.post_message(
            messages.InputFailed(
                update.text,
                update.failure.description,
                recover_draft=False,
                agent=self.agent,
                session_id=self.session_id,
            )
        )

    @handles(TranscriptChangedUpdate)
    def transcript_changed(self, update: TranscriptChangedUpdate) -> None:
        self.agent.post_message(messages.TranscriptChanged(update.cursor))

    @handles(TurnStartedUpdate)
    def turn_started(self, update: TurnStartedUpdate) -> None:
        agent = self.agent
        if self.session_id != agent.session_id or agent._stopping:
            return
        agent.uses_turn_events = True
        agent._active_turn_id = update.turn_id
        agent._turn_lifecycle_sequence += 1
        agent.post_message(
            messages.TurnStarted(
                update.turn_id,
                update.started_at,
                update.activity,
                update.activity_detail,
                agent=agent,
                session_id=self.session_id,
                sequence=agent._turn_lifecycle_sequence,
            )
        )

    @handles(TurnSettledUpdate)
    def turn_settled(self, update: TurnSettledUpdate) -> None:
        agent = self.agent
        if self.session_id != agent.session_id or agent._stopping:
            return
        if (
            agent._active_turn_id is not None
            and update.turn_id != agent._active_turn_id
        ):
            return
        if update.turn_id is not None:
            agent.uses_turn_events = True
        agent._active_turn_id = None
        agent._turn_lifecycle_sequence += 1
        agent.post_message(
            messages.TurnSettled(
                update.turn_id,
                agent=agent,
                session_id=self.session_id,
                sequence=agent._turn_lifecycle_sequence,
            )
        )

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
                    messages.InputStarted(
                        update.text, agent=self.agent, session_id=self.session_id
                    )
                )
            return
        starts = self.agent.queue_attachment.started(update, self.session_id)
        self.agent._post_queue_view(starts)

    @handles(CoordinationChangedUpdate)
    def coordination_changed(self, update: CoordinationChangedUpdate) -> None:
        from dataclasses import replace
        from pathlib import Path
        from .maintenance_ingress import configured_root
        from .agent import ContextUsage
        from textual.content import Content

        agent = self.agent
        attached_env = (agent._maintenance_env or __import__("os").environ).copy()
        attached_env["AGENT_COMMS_ROOT"] = update.wire_root
        root = configured_root(
            attached_env, agent._maintenance_cwd or agent.project_root_path.resolve()
        )
        agent.coordination = replace(update, wire_root=str(root))
        agent.project_root_path = Path(update.worktree)
        agent.uses_turn_events = agent.server_titles = agent.supports_prompt_queue = (
            True
        )
        agent.supports_prompt_images = True
        if update.context_usage is None:
            agent._context_usage = None
            agent._context_usage_saved = False
            agent.post_message(
                messages.UpdateStatusLine(Content("Context estimate unavailable"))
            )
        else:
            agent._context_usage = ContextUsage(
                update.context_usage.used, update.context_usage.size
            )
            agent._context_usage_saved = True
            agent.update_status_line()
        agent.post_message(
            messages.CommsUpdated(agent.coordination, agent, self.session_id)
        )
        title = agent._pending_session_name or update.title
        agent.post_message(messages.SessionInfoUpdate(title))
        if agent._pending_session_name is not None:
            agent._rename_coordination_thread(agent._pending_session_name)
            agent._pending_session_name = None

    @handles(GoalChangedUpdate)
    def goal_changed(self, update: GoalChangedUpdate) -> None:
        self.agent.post_message(
            messages.CommsUpdated(update, self.agent, self.session_id)
        )

    @handles(CompactionChangedUpdate)
    def compaction_changed(self, update: CompactionChangedUpdate) -> None:
        self.agent._context_usage = None
        self.agent.post_message(
            messages.CommsUpdated(update, self.agent, self.session_id)
        )

    @handles(CompactionCommittedUpdate)
    def compaction_committed(self, update: CompactionCommittedUpdate) -> None:
        self.compaction_receipt = update

    @handles(TranscriptSnapshotUpdate)
    def transcript_snapshot(self, update: TranscriptSnapshotUpdate) -> None:
        if not self.agent._reconnecting:
            self.agent.post_message(
                messages.CommsUpdated(update, self.agent, self.session_id)
            )

    @handles(InputDeliveryChangedUpdate)
    def input_delivery_changed(self, update: InputDeliveryChangedUpdate) -> None:
        self.agent.post_message(messages.InputDispositionsChanged())

    @handles(CompactionPublishedUpdate)
    def compaction_published(self, update: CompactionPublishedUpdate) -> None:
        self.agent.post_message(
            messages.CommsUpdated(update, self.agent, self.session_id)
        )

    @handles(McpClientReceiptUpdate)
    def mcp_receipt(self, update: McpClientReceiptUpdate) -> None:
        if (
            self.session_id != self.agent.session_id
            or update.turn_id != self.agent._active_turn_id
        ):
            self.agent.log(
                "[ACP MCP live receipt rejected] receipt is not bound to the active session/turn"
            )
            return
        self.agent.post_message(
            messages.CommsUpdated(update, self.agent, self.session_id)
        )
