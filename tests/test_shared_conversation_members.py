"""What both frontends' conversations answer the same way is answered by a parent they share."""

from __future__ import annotations

from toad.client.session_sources import SourcedConversation
from toad.status_thread import WorkingStatusOwner
from toad.transcript_scope import TranscriptView


def test_both_conversations_read_their_scope_status_and_loading_from_the_shared_parents():
    from toad.qt.conversation import QtConversation
    from toad.widgets.conversation import Conversation

    for conversation in (Conversation, QtConversation):
        assert conversation.thread_scope is TranscriptView.thread_scope, conversation
        assert conversation.status_thread is TranscriptView.status_thread, conversation
        assert conversation.history_loading is WorkingStatusOwner.history_loading, conversation
        assert conversation.external_transcript_changed is SourcedConversation.external_transcript_changed
        # One name for "the thread's source changed outside this view".
        assert not hasattr(conversation, "transcript_changed"), conversation


def test_a_wire_view_still_answers_status_and_loading_from_its_page_source():
    from toad.qt.window import ConversationView
    from toad.widgets.comms_chat import CommsChatView

    for view in (CommsChatView, ConversationView):
        assert "status_thread" in vars(view) and "history_loading" in vars(view), view
