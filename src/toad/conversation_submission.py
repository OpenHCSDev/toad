"""One submission transaction owns input intent, request identity and draft recovery."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, ClassVar

from acp.exceptions import RequestError
from agent_comms.acp_extension import (
    InputStartedUpdate,
    PendingQueueProjection,
    QueuePromptRequest,
    QueueScope,
    SteerPromptRequest,
)
from agent_comms.declared_family import DeclaredFamily

from toad import messages
from toad.acp.client_session import ClientSessionRequest
from toad.command_catalog import CommandCatalog
from toad.core.input_events import UserInputSubmitted
from toad.core_event_carrier import CoreEventMessage
from toad.widgets.prompt import Prompt
from agent_comms.notification_evidence import NotificationWindow

if TYPE_CHECKING:
    from toad.acp.agent import Agent
    from toad.submission_queue import QueueSource, MessageQueueEntry
    from agent_comms.ui_model.observation import ReadNotifications
    from toad.widgets.conversation import Conversation


@dataclass(frozen=True)
class InputSubmission(DeclaredFamily, affix="InputSubmission"):
    source_text: str
    priority: ClassVar[int] = 0

    @property
    def text(self):
        return self.source_text.strip()

    @classmethod
    @abstractmethod
    def matches(cls, event: UserInputSubmitted, view: Conversation): ...

    @abstractmethod
    async def execute(self, owner: ConversationSubmissions): ...

    @classmethod
    def from_event(cls, event: UserInputSubmitted, view: Conversation):
        kind = next(
            kind
            for kind in sorted(cls.members_with(InputSubmission), key=lambda kind: kind.priority, reverse=True)
            if kind.matches(event, view)
        )
        return kind(event.body)


class NoInputSubmission(InputSubmission):
    priority = -1

    @classmethod
    def matches(cls, event: UserInputSubmitted, view: Conversation):
        return True

    async def execute(self, owner: ConversationSubmissions):
        pass


class QueueNowInputSubmission(InputSubmission):
    priority = 100

    @classmethod
    def matches(cls, event: UserInputSubmitted, view: Conversation):
        if event.shell or event.body.strip():
            return False
        return event.immediate and view.agent_binding.presentation.queue_supported

    async def execute(self, owner: ConversationSubmissions):
        projection = owner.queue_projection
        if projection.status == "available" and projection.items:
            owner.send_now()


class ShellInputSubmission(InputSubmission):
    priority = 90

    @classmethod
    def matches(cls, event: UserInputSubmitted, view: Conversation):
        return event.shell and bool(event.body.strip())

    async def execute(self, owner):
        view = owner.view
        shell = view.shell
        if await shell.is_busy():
            shell.focus_output()
            await shell.send_input(self.source_text, paste=True)
        else:
            view.run_worker(partial(view.input_histories.shell.record, self.source_text), group="history")
            await view.post_shell(self.source_text)
        view.jump_to_latest()


class SubmissionStart(ABC):
    """The result of acquiring a submission's source, not an optional request."""

    @abstractmethod
    async def prepare(self): ...


class UnboundSubmissionStart(SubmissionStart):
    def __init__(self, owner: ConversationSubmissions, submission: AgentInputSubmission):
        self.owner, self.submission = owner, submission

    async def prepare(self):
        self.owner.view.delivery_refused(
            "No connected owner; your input has not been submitted", self.submission.source_text
        )


class AgentInputSubmission(InputSubmission):
    @property
    @abstractmethod
    def request(self): ...

    async def feedback(self, execution: SubmissionExecution):
        view = execution.owner.view
        await view.turns.binding.present_input(view, self.text)
        if execution.retired:
            return
        view.jump_to_latest()
        await view.auto_name_from_prompt(self.text)
        if execution.retired:
            return
        waiting = "Waiting for replies…" if self.text.startswith(("@", "#", "!relay ")) else "Thinking…"
        view.turns.describe(waiting)
        await asyncio.sleep(0)

    async def execute(self, owner: ConversationSubmissions):
        view = owner.view
        return await owner.begin(self).prepare()


class OrdinaryInputSubmission(AgentInputSubmission):
    @classmethod
    def matches(cls, event: UserInputSubmitted, view: Conversation):
        if event.shell:
            return False
        return bool(event.body.strip())

    @property
    def request(self):
        return QueuePromptRequest(self.text)


class DeferredInputSubmission(OrdinaryInputSubmission):
    priority = 70

    @classmethod
    def matches(cls, event: UserInputSubmitted, view: Conversation):
        if not super().matches(event, view):
            return False
        if event.immediate:
            return False
        return view.turns.owner.busy and view.agent_binding.presentation.queue_supported

    @property
    def request(self):
        return QueuePromptRequest(self.text, True)

    async def feedback(self, execution: SubmissionExecution):
        # Native queue/start publications own confirmation and message display.
        pass


class ImmediateInputSubmission(OrdinaryInputSubmission):
    priority = 80

    @classmethod
    def matches(cls, event: UserInputSubmitted, view: Conversation):
        if not super().matches(event, view):
            return False
        return event.immediate and view.agent_binding.presentation.queue_supported

    @property
    def request(self):
        return SteerPromptRequest(self.text)


class SubmissionExecution(SubmissionStart):
    """Immutable source binding and the real outstanding local request."""

    def __init__(self, owner: ConversationSubmissions, submission: AgentInputSubmission, agent: Agent):
        self.owner, self.submission, self.agent = owner, submission, agent
        self.authority = ClientSessionRequest(agent, agent.session_id)
        self.scope = agent.queue_attachment.scope
        self.request = submission.request
        self.started_update: InputStartedUpdate | None = None

    async def prepare(self):
        owner, submission = self.owner, self.submission
        view = owner.view
        owner.publish_pending()
        view.run_worker(partial(view.input_histories.prompt.record, submission.source_text), group="history")
        try:
            await submission.feedback(self)
            if self.current:
                return view.run_worker(partial(self.send), group="conversation-submission")
            owner.finish(self)
        except BaseException:
            owner.finish(self)
            raise

    @property
    def current(self):
        view = self.owner.view
        if view.agent_binding is not self.agent or self.authority.retired:
            return False
        return self.agent.queue_attachment.accepts_request(self.scope)

    @property
    def retired(self):
        return not self.current

    async def send(self):
        view = self.owner.view
        managed = self.agent.presentation.uses_managed_turns
        local = not managed
        reason = None
        if local:
            view.turns.start_client()
        try:
            if self.agent.presentation.queue_supported:
                reason = await self.agent.send_prompt(self.submission.text, request=self.request)
            else:
                reason = await self.agent.send_prompt(self.submission.text)
        except RequestError as error:
            if self.current:
                from toad.widgets.conversation import INTERNAL_EROR
                from toad.widgets.markdown_note import MarkdownNote

                view.turns.finish_client()
                view.prompt.restore_draft(self.submission.text)
                await view.post(
                    MarkdownNote(
                        INTERNAL_EROR.replace("$ERROR", str(error) or "no details were provided"),
                        classes="-stop-reason",
                    )
                )
        finally:
            self.owner.finish(self)
        if self.current and local:
            view.call_later(self.complete, reason)

    async def complete(self, reason):
        if self.current:
            await self.owner.view.agent_turn_over(reason)


class ConversationSubmissions:
    """Own pending local transactions; remote membership stays with QueueAttachment."""

    def __init__(self, view):
        self.view = view
        self.active: list[SubmissionExecution] = []

    def begin(self, submission: AgentInputSubmission):
        return self.view.agent_binding.begin_submission(self, submission)

    def unbound(self, submission: AgentInputSubmission):
        return UnboundSubmissionStart(self, submission)

    def start(self, submission: AgentInputSubmission, agent: Agent):
        execution = SubmissionExecution(self, submission, agent)
        self.active.append(execution)
        return execution

    @property
    def ready(self):
        return self.view.operational_sources.input_ready(self.view)

    @property
    def unavailable_reason(self):
        return self.view.operational_sources.unavailable_reason(self.view)

    async def submit(self, event: UserInputSubmitted):
        text = event.body.strip()
        if not event.shell and text.startswith("/") and await CommandCatalog.execute(text, self.view):
            return
        return await self.view.operational_sources.submit(self, event)

    def accepts_failure(self, message: CoreEventMessage):
        return self.view.agent_binding.accepts_failed_input(message)

    @property
    def queue_source(self) -> QueueSource:
        return self.view.queue_source

    @property
    def queue_summary(self) -> str:
        return self.queue_source.queue_summary(self)

    @property
    def message_queue_entries(self) -> tuple[MessageQueueEntry, ...]:
        """Borrow the existing visible fragment proofs; never retain another inbox."""
        entries: dict[ReadNotifications, MessageQueueEntry] = {}
        for target in self.view.contents.notification_targets():
            for fragment in target.visible_fragments():
                for entry in fragment.queue_entries(target.notification_view):
                    entries[entry.request] = entry
                    if len(entries) >= NotificationWindow.window_limit:
                        return tuple(entries.values())
        return tuple(entries.values())

    def inspect_queue(self):
        from toad.submission_queue import QueueInspection

        inspection = QueueInspection(self)
        self.view.app.push_screen(inspection)
        return inspection

    @property
    def queue_projection(self):
        return self.view.agent_binding.presentation.queue

    @property
    def queued_inputs(self):
        """Accepted producer rows not yet handed to their original native body."""
        return self.queue_projection.items

    @property
    def delivering(self):
        queue = self.queue_projection
        accepted = {row.input_id for row in (*queue.items, *queue.restored)}
        return tuple(
            item.submission.text
            for item in self.active
            if item.current
            and item.agent.presentation.uses_managed_turns
            and item.request.input_id not in accepted
            and item.started_update is None
        )

    def native_input_presented(self, started: InputStartedUpdate):
        """Retain this request's actual response while its RPC is outstanding."""
        for execution in self.active:
            if execution.current and started.started_request(execution.request.input_id):
                execution.started_update = started

    def publish_pending(self):
        if (prompt := self.view.query_one_optional(Prompt)) is not None:
            prompt.sync_queue()

    def finish(self, execution: SubmissionExecution):
        if execution in self.active:
            self.active.remove(execution)
        if execution.current:
            self.publish_pending()

    def reset(self):
        self.active.clear()
        self.publish_pending()

    def send_now(self):
        source = self.queue_source
        return self.view.run_worker(
            partial(self._send_now, source, self.view.agent_binding, source.queue_scope(self)),
            group="send-queued-now", exclusive=True,
        )

    async def _send_now(self, source: QueueSource, agent, scope: QueueScope) -> None:
        try:
            if self.queue_source is not source or self.view.agent_binding is not agent:
                raise ValueError("The source changed before send now")
            await source.queue_send_now(self, scope)
        except (RequestError, ValueError) as error:
            if self.queue_source is source and self.view.agent_binding is agent:
                self.view.feedback.flash(f"Send now failed: {error}", style="error")
        self.publish_pending()
