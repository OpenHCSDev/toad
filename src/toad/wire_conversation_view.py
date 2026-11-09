"""A conversation with a wire-backed, read-marked history."""
from abc import abstractmethod

from agent_comms.message_reference import MessageReference

from toad.conversation_capabilities import ConversationActivity
from toad.conversation_kind import ConversationKind
from toad.read_marked_history import ReadMarkedHistory
from toad.widgets.conversation import Conversation


class WireConversationView(Conversation, ConversationActivity):
    """The existing conversation widget supplies the native view behavior."""

    conversation: ConversationKind
    message_history: ReadMarkedHistory

    @abstractmethod
    async def show_sent(self, sent: MessageReference) -> None: ...

    @abstractmethod
    async def _refresh_source(self) -> None: ...
