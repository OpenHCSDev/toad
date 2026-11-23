"""A conversation with a wire-backed, read-marked history, drawn by Textual."""
from pathlib import Path

from toad.client.conversation import ConversationKind
from toad.client.history import WireView
from toad.session_scope import SessionScope
from toad.widgets.conversation import Conversation


class WireConversationView(WireView, Conversation):
    """The existing conversation widget supplies the native view behavior."""

    @property
    def mode(self) -> str:
        return self.query_ancestor(SessionScope).id

    def wire_view_open(self) -> bool:
        return self.is_attached
