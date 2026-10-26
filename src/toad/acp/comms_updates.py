"""Consume declared Comms facts through the shared nominal dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.acp_extension import (
    CompactionChangedUpdate,
    CompactionCommittedUpdate,
    CoordinationChangedUpdate,
    CursorAdvancedUpdate,
    GoalChangedUpdate,
    InputDeliveryChangedUpdate,
    InputFailedUpdate,
    InputStartedUpdate,
    McpClientAcknowledgementUpdate,
    NativeOutputCommittedUpdate,
    NativeRoundCommittedUpdate,
    PromptCancelledUpdate,
    QueueChangedUpdate,
    RequestFailedUpdate,
    SelectedWriteAcceptedUpdate,
    TextNoticeUpdate,
    TextRouteUpdate,
    TranscriptChangedUpdate,
    TranscriptSnapshotUpdate,
    TurnChangedUpdate,
)
from agent_comms.context_reading import UnmeasuredContext
from agent_comms.errors import RouteChangedError
from agent_comms.native_output import AssistantOutput, ToolOutput
from agent_comms.thread_presentation import NoThreadPresentation, ThreadPresentation
from agent_comms.transcripts import NativeCommittedPrefix
from metaclass_registry.mro_dispatch import MroDispatch, handles

from toad.acp.client_session import ClientSessionRequest
from toad.acp.context_measurement import ContextMeasurement
from toad.core import events as core_events
from toad.live_output import CompleteResponseStream, ResponseStream
from toad.response_delivery import ResponseDelivery, UnroutedResponse

if TYPE_CHECKING:
    from toad.acp.agent import Agent


class CompactionReply:
    """The reply owns whether /compact supplied a committed summary."""

    def require(self) -> CompactionCommittedUpdate:
        raise ValueError("Compaction result was missing")


@dataclass(frozen=True)
class CommittedCompactionReply(CompactionReply):
    update: CompactionCommittedUpdate

    def require(self) -> CompactionCommittedUpdate:
        return self.update


class CommsUpdateConsumer(MroDispatch):
    def __init__(
        self,
        agent,
        session_id: str,
        *,
        cursor_token: int | None = None,
        queue_token: int | None = None,
    ) -> None:
        self.agent = agent
        self.session_id = session_id
        self.delivery: ResponseDelivery = UnroutedResponse()
        self.response_type: type[ResponseStream] = ResponseStream
        self.compaction: CompactionReply = CompactionReply()
        self.cursor_token = cursor_token
        self.queue_token = queue_token

    async def consume_metadata(self, metadata) -> None:
        from .sdk_boundary import DecodeCommsMetadataTask

        authority = ClientSessionRequest(self.agent, self.session_id)
        facts = await self.agent.controller.task_runner.run(
            DecodeCommsMetadataTask(metadata)
        )
        authority.require()
        for fact in facts:
            self.dispatch_sync(fact)

    def accepts_turn(self):
        return self.agent.session.accepts_session(self.session_id)

    @handles(TextRouteUpdate)
    def text_route(self, update: TextRouteUpdate) -> None:
        self.delivery = ResponseDelivery.from_route(update.route)

    @handles(TextNoticeUpdate)
    def text_notice(self, update: TextNoticeUpdate) -> None:
        self.response_type = CompleteResponseStream

    def response_stream(self) -> ResponseStream:
        """Ingress text kind and its original append claim determine the stream."""
        return self.response_type(
            self.delivery,
            source_claim=self.agent.controller.session.output.assistant,
        )

    @handles(InputFailedUpdate)
    def input_failed(self, update: InputFailedUpdate) -> None:
        self.agent.events.publish(
            core_events.CommsUpdated(
                update, recover_draft=False, session_id=self.session_id
            )
        )

    @handles(TranscriptChangedUpdate)
    def transcript_changed(self, update: TranscriptChangedUpdate) -> None:
        self.agent.events.publish(core_events.CommsUpdated(update, self.session_id))

    @handles(NativeOutputCommittedUpdate)
    def native_output_committed(self, update: NativeOutputCommittedUpdate) -> None:
        self.dispatch_sync(update.output, update.identity)

    @handles(AssistantOutput)
    def assistant_committed(self, output: AssistantOutput, source: NativeCommittedPrefix) -> None:
        self.agent.controller.session.output.assistant_committed(source)

    @handles(ToolOutput)
    def tool_committed(self, output: ToolOutput, source: NativeCommittedPrefix) -> None:
        self.agent.tools.committed(output.tool_call_id, source)

    @handles(NativeRoundCommittedUpdate)
    def native_round_committed(self, update: NativeRoundCommittedUpdate) -> None:
        self.agent.controller.session.output.round_committed(update.identity)
        self.agent.events.publish(core_events.CommsUpdated(update, self.session_id))

    @handles(TurnChangedUpdate)
    def turn_changed(self, update: TurnChangedUpdate) -> None:
        if not self.accepts_turn():
            return
        agent = self.agent
        binding = agent.presentation.managed_turns()
        if not binding.receive(update.state):
            return
        agent.events.publish(
            core_events.CommsUpdated(
                update, session_id=self.session_id, sequence=binding.sequence
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
        update.when_unidentified(lambda: self._post_unidentified(update))
        if update.scope.matches_session(self.session_id):
            starts = self.agent.queue_attachment.started(update, self.session_id)
            self.agent._post_queue_view(starts)

    def _post_unidentified(self, update: InputStartedUpdate) -> None:
        if self.session_id == self.agent.session_id:
            self.agent.events.publish(
                core_events.CommsUpdated(update, session_id=self.session_id)
            )

    @handles(CoordinationChangedUpdate)
    def coordination_changed(self, update: CoordinationChangedUpdate) -> None:
        agent = self.agent
        root = agent.controller.transcripts.access.launch_root.path
        if Path(update.wire_root).resolve() != root.resolve():
            raise RouteChangedError("ACP owner reported a different coordination root")
        agent.coordination = update
        agent.project_root_path = update.worktree.path
        agent.context_measurement = ContextMeasurement.saved(update.context_usage)
        agent.update_status_line()
        agent.events.publish(
            core_events.CommsUpdated(agent.coordination, self.session_id)
        )
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
        self.compaction = CommittedCompactionReply(update)

    @handles(TranscriptSnapshotUpdate)
    def transcript_snapshot(self, update: TranscriptSnapshotUpdate) -> None:
        controller = self.agent.controller
        controller.start_operation(
            controller.publish_transcript_snapshot(
                update, controller.surface, controller.session
            )
        )

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
    def selected_write_accepted(self, update) -> None:
        pass

    @handles(RequestFailedUpdate)
    def request_failed(self, update) -> None:
        from toad.core.events import RequestAgentFail

        # One request failed; the session that carried it is still open.
        self.agent.events.publish(
            RequestAgentFail(update, self.agent.presentation.log_path)
        )

    @handles(PromptCancelledUpdate)
    def prompt_cancelled(self, update) -> None:
        self.agent.events.publish(core_events.CommsUpdated(update, self.session_id))


class OwnerSnapshotConsumer(CommsUpdateConsumer):
    """Canonical reads reconcile a turn without overtaking this client's request."""

    def __init__(self, agent, session_id, *, turn_token) -> None:
        super().__init__(agent, session_id)
        self.turn_token = turn_token

    def accepts_turn(self):
        return super().accepts_turn() and self.agent.controller.accepts_turn_snapshot(
            self.turn_token
        )

    @handles(NoThreadPresentation)
    def missing_thread_presentation(self, presentation: NoThreadPresentation) -> object:
        return self.DISCARD

    @handles(ThreadPresentation)
    def thread_presentation(self, presentation: ThreadPresentation) -> None:
        identity = presentation.read_identity
        if identity is None:
            return  # An unavailable source supplies no turn settlement.
        identity.publish_turn(self.publish_thread_turn)

    def publish_thread_turn(self, root, thread):
        """Only the live transcript member can supply actual owner settlement."""
        coordination = self.agent.coordination
        self.agent.controller.require_owner(
            coordination, ClientSessionRequest(self.agent, self.session_id)
        )
        if root != coordination.wire_root or thread.incarnation != coordination.thread:
            raise ValueError("Turn snapshot belongs to another original thread source")
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
    presentation: ThreadPresentation

    def present(self, consumer) -> None:
        consumer(self.presentation)


class ThreadRead:
    """A presentation read, with settlement owned by its captured source."""

    def settle(self, presentation: ThreadPresentation) -> ThreadReadOutcome:
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

    agent: Agent
    coordination: CoordinationChangedUpdate
    authority: ClientSessionRequest
    snapshot: OwnerSnapshotConsumer

    def settle(self, presentation: ThreadPresentation) -> ThreadReadOutcome:
        current = self.agent.coordination
        if current is None or (current.wire_root, current.thread) != (
            self.coordination.wire_root,
            self.coordination.thread,
        ):
            return ChangedAttachmentRead()
        if self.authority.retired:
            return EndedSessionRead()
        self.snapshot.dispatch_sync(presentation)
        return SettledThreadRead(presentation)

    async def reconcile(self, transcripts) -> None:
        read = await transcripts.thread_presentation(
            self.coordination.wire_root, self.coordination.thread.name
        )
        self.settle(read.raised())
