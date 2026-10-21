"""Consume declared Comms facts through the shared nominal dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_comms.acp_extension import (
    CompactionChangedUpdate,
    CompactionCommittedUpdate,
    CoordinationChangedUpdate,
    CursorAdvancedUpdate,
    GoalChangedUpdate,
    InputDeliveryChangedUpdate,
    InputFailedUpdate,
    InputStartedUpdate,
    PromptCancelledUpdate,
    McpClientAcknowledgementUpdate,
    QueueChangedUpdate,
    RequestFailedUpdate,
    SelectedWriteAcceptedUpdate,
    TextRouteUpdate,
    TranscriptChangedUpdate,
    TranscriptSnapshotUpdate,
    TurnChangedUpdate,
)
from agent_comms.context_reading import UnmeasuredContext
from agent_comms.mro_dispatch import MroDispatch, handles
from agent_comms.thread_presentation import ThreadPresentation
from toad.acp.client_session import ClientSessionRequest
from toad.acp.context_measurement import ContextMeasurement

from toad.core import events as core_events


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
        self.compaction_update = None
        self.cursor_token = cursor_token
        self.queue_token = queue_token

    async def consume_metadata(self, metadata):
        from .sdk_boundary import DecodeCommsMetadataTask

        authority = ClientSessionRequest(self.agent, self.session_id)
        facts = await self.agent.controller.task_runner.run(DecodeCommsMetadataTask(metadata))
        authority.require()
        for fact in facts:
            self.dispatch_sync(fact)

    def accepts_turn(self):
        return self.agent.session.accepts_session(self.session_id)

    def require_compaction_update(self):
        if self.compaction_update is None:
            raise ValueError('Compaction result was missing')
        return self.compaction_update

    @handles(TextRouteUpdate)
    def text_route(self, update: TextRouteUpdate) -> None:
        self.route = update.route

    @handles(InputFailedUpdate)
    def input_failed(self, update: InputFailedUpdate) -> None:
        self.agent.events.publish(core_events.CommsUpdated(update, recover_draft=False, session_id=self.session_id))

    @handles(TranscriptChangedUpdate)
    def transcript_changed(self, update: TranscriptChangedUpdate) -> None:
        self.agent.events.publish(core_events.CommsUpdated(update, self.session_id))

    @handles(TurnChangedUpdate)
    def turn_changed(self, update: TurnChangedUpdate) -> None:
        if not self.accepts_turn():
            return
        agent = self.agent
        binding = agent.presentation.managed_turns()
        if not binding.receive(update.state):
            return
        agent.events.publish(core_events.CommsUpdated(update, session_id=self.session_id, sequence=binding.sequence))

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
        if update.scope.unidentified_start(update.input_id):
            if self.session_id == self.agent.session_id:
                self.agent.events.publish(core_events.CommsUpdated(update, session_id=self.session_id))
        elif update.scope.matches_session(self.session_id):
            starts = self.agent.queue_attachment.started(update, self.session_id)
            self.agent._post_queue_view(starts)

    @handles(CoordinationChangedUpdate)
    def coordination_changed(self, update: CoordinationChangedUpdate) -> None:
        from pathlib import Path
        from agent_comms.errors import RouteChangedError

        agent = self.agent
        root = agent.controller.transcripts.access.launch_root.path
        if Path(update.wire_root).resolve() != root.resolve():
            raise RouteChangedError("ACP owner reported a different coordination root")
        agent.coordination = update
        agent.project_root_path = Path(update.worktree)
        agent.context_measurement = ContextMeasurement.saved(update.context_usage)
        agent.update_status_line()
        agent.events.publish(core_events.CommsUpdated(agent.coordination, self.session_id))
        agent.session.coordinated_title(update.title)

    @handles(GoalChangedUpdate)
    def goal_changed(self, update: GoalChangedUpdate) -> None:
        self.agent.events.publish(core_events.CommsUpdated(update, self.session_id))

    @handles(CompactionChangedUpdate)
    def compaction_changed(self, update: CompactionChangedUpdate) -> None:
        self.agent.context_measurement = ContextMeasurement.saved(UnmeasuredContext())
        self.agent.update_status_line()
        self.agent.events.publish(core_events.CommsUpdated(update, self.session_id))

    @handles(CompactionCommittedUpdate)
    def compaction_committed(self, update: CompactionCommittedUpdate) -> None:
        self.compaction_update = update

    @handles(TranscriptSnapshotUpdate)
    def transcript_snapshot(self, update: TranscriptSnapshotUpdate) -> None:
        controller = self.agent.controller
        controller.start_operation(controller.publish_transcript_snapshot(
            update, controller.surface, controller.session))

    @handles(InputDeliveryChangedUpdate)
    def input_delivery_changed(self, update: InputDeliveryChangedUpdate) -> None:
        from toad.core.events import InputDispositionsChanged
        self.agent.events.publish(InputDispositionsChanged())

    @handles(McpClientAcknowledgementUpdate)
    def mcp_status(self, update: McpClientAcknowledgementUpdate) -> None:
        if (
            self.session_id != self.agent.session_id
            or update.turn_id != self.agent.current_turn.managed_id
        ):
            self.agent.log(
                "[ACP MCP live receipt rejected] receipt is not bound to the active session/turn"
            )
            return
        self.agent.events.publish(core_events.CommsUpdated(update, self.session_id))

    @handles(SelectedWriteAcceptedUpdate)
    def selected_write_accepted(self, update):
        pass

    @handles(RequestFailedUpdate)
    def request_failed(self, update):
        from toad.core.events import RequestAgentFail

        self.agent.session.record_failure(
            RequestAgentFail(update, self.agent.presentation.log_path)
        )

    @handles(PromptCancelledUpdate)
    def prompt_cancelled(self, update):
        self.agent.events.publish(core_events.CommsUpdated(update, self.session_id))


class OwnerSnapshotConsumer(CommsUpdateConsumer):
    """Canonical reads reconcile a turn without overtaking this client's request."""

    def __init__(self, agent, session_id, *, turn_token):
        super().__init__(agent, session_id)
        self.turn_token = turn_token

    def accepts_turn(self):
        return (super().accepts_turn()
                and self.agent.controller.accepts_turn_snapshot(self.turn_token))

    @handles(ThreadPresentation)
    def thread_presentation(self, presentation):
        identity = presentation.read_identity
        if identity is None:
            return  # An unavailable source supplies no turn settlement.
        identity.publish_turn(self.publish_thread_turn)

    def publish_thread_turn(self, root, thread):
        """Only the live transcript member can supply actual owner settlement."""
        coordination = self.agent.coordination
        self.agent.controller.require_owner(
            coordination, ClientSessionRequest(self.agent, self.session_id))
        if (root != coordination.wire_root or thread.incarnation != coordination.thread):
            raise ValueError('Turn snapshot belongs to another original thread source')
        self.turn_changed(TurnChangedUpdate(thread.turn_state))


class ThreadReadOutcome:
    """A status read may publish only while its captured source still holds."""

    def present(self, consumer) -> None:
        """Expired observations leave the newer session's presentation alone."""


class EndedSessionRead(ThreadReadOutcome):
    """The read's client session ended before its result arrived."""


class ChangedAttachmentRead(ThreadReadOutcome):
    """The read's original thread is no longer attached to this client."""


@dataclass(frozen=True)
class SettledThreadRead(ThreadReadOutcome):
    presentation: ThreadPresentation | None

    def present(self, consumer) -> None:
        consumer(self.presentation)


class ThreadRead:
    """A presentation read, with settlement owned by its captured source."""

    def settle(self, presentation: ThreadPresentation | None) -> ThreadReadOutcome:
        return SettledThreadRead(presentation)

    async def reconcile(self, transcripts) -> None:
        """An uncaptured read has no owner snapshot to reconcile."""


class NoPendingThreadRead(ThreadRead):
    """No captured client authority; present the current observation directly."""


@dataclass(frozen=True)
class PendingThreadRead(ThreadRead):
    """One presentation read of an agent's thread, captured before the read.

    Whether the read ran here or in Core's observation process, its result
    settles the turn only if the attachment and client session it was
    requested for still hold.
    """

    agent: Any
    coordination: CoordinationChangedUpdate
    authority: ClientSessionRequest
    snapshot: OwnerSnapshotConsumer

    def settle(self, presentation: ThreadPresentation | None) -> ThreadReadOutcome:
        current = self.agent.coordination
        if current is None or (current.wire_root, current.thread) != (
            self.coordination.wire_root, self.coordination.thread
        ):
            return ChangedAttachmentRead()
        if self.authority.retired:
            return EndedSessionRead()
        if presentation is not None:
            self.snapshot.dispatch_sync(presentation)
        return SettledThreadRead(presentation)

    async def reconcile(self, transcripts) -> None:
        self.settle(await transcripts.thread_presentation(
            self.coordination.wire_root, self.coordination.thread.name))