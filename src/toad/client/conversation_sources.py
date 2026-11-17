"""The contract a conversation's owning session answers to the conversation itself: its status
row, agent label, prompt, input decision and submissions, and the hooks for a presented thread
and a started agent.

Declared toolkit-neutral under `toad.client` so both Textual's `widgets.conversation.Conversation`
and Qt's `qt.acp_tab.QtAcpSessionView` can carry a `queue_source` typed by this ABC and both
backends call `.begin_submission(...)`, `.prompt(...)` and friends through the one declaration.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from toad.client.input_decision import InputDecision
from toad.client.submission import SubmissionStart
from toad.conversation_submission import AgentInputSubmission, ConversationSubmissions
from toad.submission_queue import QueueSource

if TYPE_CHECKING:
    from toad.widgets.conversation import Conversation


class ConversationSources(QueueSource):
    """What a conversation asks of the sources its session presents: its status row, agent
    label, prompt, input decision and submissions, and the hooks for a presented thread and a
    started agent."""

    @abstractmethod
    def status_row(self, conversation: Conversation): ...

    @abstractmethod
    def agent_info(self, conversation: Conversation) -> str: ...

    @abstractmethod
    def thread_presented(self, conversation: Conversation) -> None: ...

    @abstractmethod
    def prompt(self, conversation: Conversation): ...

    @abstractmethod
    def begin_submission(self, owner: ConversationSubmissions, submission: AgentInputSubmission) -> SubmissionStart: ...

    @abstractmethod
    def input_decision(self, conversation: Conversation) -> InputDecision: ...

    @abstractmethod
    def start_agent(self, conversation: Conversation) -> None: ...

    @abstractmethod
    def external_transcript_changed(self, conversation: Conversation) -> None: ...
