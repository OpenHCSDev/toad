"""Where a conversation view's input and queue go, decided once for every frontend.

`SessionSources` answers for a view whose input is a prompt to its agent; `MailboxSources`
for a CLI thread, whose input is a message to Core's inbox, queued like a prompt.
`SourcedConversation` is what both views inherit to read them: their `queue_source` and
where a submission begins. Textual adds its prompt widgets and agent start on subclasses
in `toad.session_presentation`; Qt uses these directly.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from agent_comms.messaging.message_reference import MessageReference
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.registry.thread_presentation import EnsuringSessionLoadPlan

from toad.acp.agent import Agent
from toad.agent_binding import NoAgentConnection
from toad.core import events as core_events
from toad.client.connection import Observing
from toad.client.conversation_sources import ConversationSources
from toad.client.goal_source import CommsGoalSource
from toad.client.input_decision import InputDecision
from toad.goal_controls import GoalSource
from toad.submission_queue import BusQueueSource, NativeQueueSource, QueueSource
from toad.transcript_publication import CanonicalSourcePublication
from toad.transcript_scope import MailboxSent, TranscriptView


class SessionSources(ConversationSources, NativeQueueSource):
    """An operational view: its input is a prompt for its agent."""

    def __init__(self) -> None:
        self.agent_binding = NoAgentConnection()
        self.shell = None
        self.load_plan = EnsuringSessionLoadPlan()

    def status_row(self, conversation):
        row = self.activity_row(conversation).with_delivery(conversation.input_delivery)
        return conversation.agent_binding.session_disposition.present(row, row.disconnected)

    def activity_row(self, conversation):
        # A Core history source owns status even when its ACP load fails.
        if conversation.transcript.readable:
            return conversation.thread_activity.row
        return conversation.turns.binding.status_row(conversation.thread_activity.row)

    def agent_info(self, conversation) -> str:
        return "shell"

    def thread_presented(self, conversation) -> None:
        """A native agent reports its configuration through ACP."""

    def external_transcript_changed(self, conversation) -> None:
        """Core publishes native and CLI drafts through the same transcript store."""
        conversation.transcript.source_requests.request(CanonicalSourcePublication)

    def begin_submission(self, owner, submission):
        """An operational view's input is a prompt for its agent."""
        return owner.view.agent_binding.begin_submission(owner, submission)

    def input_decision(self, conversation) -> InputDecision:
        agent = conversation.agent_binding
        return agent.readiness_decision.then(
            lambda: agent.configuration.model.input_decision
        ).then(
            lambda: conversation.thread_scope.owner_decision(conversation.thread_presentation)
        )

    def start_agent(self, conversation) -> None:
        conversation.agent_binding.start_agent(self, conversation)

    def create_agent(self, conversation) -> None:
        """The unbound view starts a new operational agent for its launch, where this
        platform runs agent processes; where it does not, the view opens without one and
        says why."""
        conversation.app.agent_processes.start(
            partial(self.spawn_agent, conversation),
            partial(self.agent_refused, conversation))

    def agent_refused(self, conversation, reason: str) -> None:
        conversation.feedback.flash(reason)
        conversation.present_without_agent()

    def spawn_agent(self, conversation) -> None:
        """The launch's agent, resuming the view's session when it names one, borrowing the
        processes other sessions already run."""
        app = conversation.app
        agent = Agent(
            conversation.project_path.path,
            conversation.launch.require_agent(),
            conversation._agent_session_id,
            conversation._session_pk,
            app_events=app.events,
            transcripts=app.coordination_access.transcripts,
        )
        agent.session.load_plan = self.load_plan
        conversation._native_agent_started_here = True
        conversation.bind_agent(agent)
        agent.controller.start_operation(agent.start(app.session_navigation.processes))
        conversation.publish_core(core_events.SessionSubtitleChanged(conversation.agent_title))

    def goal_source(self, conversation) -> GoalSource:
        """An operational view's goal is its agent's."""
        return conversation.agent_binding


class MailboxSources(MailboxSent, BusQueueSource, SessionSources):
    """A CLI thread receives user messages through Core's inbox, not ACP."""

    def __init__(self) -> None:
        super().__init__()
        self.goal_sources: dict[ThreadIncarnation, CommsGoalSource] = {}

    def goal_source(self, conversation) -> GoalSource:
        """A CLI has no agent connection: its goal is the one the bus holds for its inbox, read
        and changed through Core as Qt's goal bar reads it (`CommsGoalSource`). One source per
        incarnation, so a press settles against the source it started on."""
        owner = conversation.goal_owner()
        if owner is None:
            return super().goal_source(conversation)
        return self.goal_sources.setdefault(
            owner, CommsGoalSource(conversation.app, owner, conversation.coordination_root))

    def capture_queue_observing(
        self, transcript: Callable[[Callable[[], Observing]], Observing],
        observing: Callable[[], Observing],
    ) -> Callable[[], Observing]:
        return partial(transcript, super().capture_queue_observing(transcript, observing))

    def activity_row(self, conversation):
        return conversation.thread_activity.row

    def agent_info(self, conversation) -> str:
        return conversation.thread_activity.row.presentation.title

    def begin_submission(self, owner, submission):
        """A CLI thread's input is a message to its inbox, queued like a prompt."""
        view = owner.view
        return view.thread_scope.begin_mailbox(owner, submission, view, self)

    async def mailbox_sent(self, view: TranscriptView, sent: MessageReference) -> None:
        """Follow the transcript's end; the inbox message shows once the thread records it."""
        view.follow_latest()
        view.transcript_changed()


class SourcedConversation:
    """A conversation view reads its queue and starts its submissions through its sources."""

    operational_sources: ConversationSources

    @property
    def queue_source(self) -> QueueSource:
        return self.operational_sources

    def begin_submission(self, owner, submission):
        """Where this view's input goes: its operational sources answer for agent and CLI views."""
        return self.operational_sources.begin_submission(owner, submission)
