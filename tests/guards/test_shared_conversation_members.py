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
        assert conversation.reload is SourcedConversation.reload
        # One name for "the thread's source changed outside this view".
        assert not hasattr(conversation, "transcript_changed"), conversation


def test_both_wire_views_answer_sends_commands_status_and_loading_from_the_shared_wire_view():
    from toad.client.history import WireView
    from toad.qt.window import ConversationView
    from toad.widgets.comms_chat import CommsChatView

    for view in (CommsChatView, ConversationView):
        for member in ("begin_submission", "command_target_context", "status_thread", "history_loading"):
            assert getattr(view, member) is getattr(WireView, member), (view, member)
        # The conversation's dispatch still answers; the wire view only names it.
        assert "dispatch_sync" not in vars(WireView)
