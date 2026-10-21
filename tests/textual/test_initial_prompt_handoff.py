"""Textual-facing: a session screen's initial prompt is handed to its conversation once, survives the
conversation widget being evicted and remounted, and keeps the editor's document and undo history."""

import asyncio
from collections import Counter

from toad.agent_binding import NoAgentConnection
from toad.core.input_events import UserInputSubmitted
from toad.screens.main import MainScreen
from toad.widgets.conversation import ConversationSessionBinding


class ObservedLaunchScreen(MainScreen):
    """Records the conversation's published inputs; creation and handlers stay native."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inputs = Counter()
        self.publication = asyncio.Event()
        self.subscriptions = []

    def observed(self, event, subscription):
        if isinstance(event, UserInputSubmitted):
            assert not event.shell
            self.inputs[event.body] += 1
            self.publication.set()

    def _make_conversation(self):
        conversation = super()._make_conversation()
        self.subscriptions.append(conversation.core_publications.subscribe(self.observed))
        return conversation


async def test_a_failed_conversation_construction_keeps_the_initial_prompt_and_a_successful_one_transfers_it(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        app, _pilot = ui.textual
        # Session title acquisition refuses an unregistered source before construction.
        candidate = MainScreen(workspace.project, initial_prompt="CONSTRUCTOR_PENDING")
        candidate.id = "not-a-registered-session"
        try:
            candidate._make_conversation()
        except KeyError:
            assert candidate._initial_prompt == "CONSTRUCTOR_PENDING"
        else:
            raise AssertionError("Unregistered source unexpectedly constructed a conversation")
        successful = MainScreen(workspace.project, initial_prompt="CONSTRUCTOR_PENDING")
        successful.id = app.selected_mode
        constructed = successful._make_conversation()
        assert successful._initial_prompt is None
        assert candidate._initial_prompt == "CONSTRUCTOR_PENDING"
        assert constructed.take_initial_prompt() == "CONSTRUCTOR_PENDING"
        assert constructed.take_initial_prompt() is None


async def test_a_pending_initial_prompt_is_published_once_across_eviction_and_the_draft_and_undo_survive(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        app, _pilot = ui.textual
        owner = ObservedLaunchScreen(workspace.project, initial_prompt="INITIAL_LOCAL_UI_EVENT")
        await app.session_navigation.new(lambda: owner)
        await owner.wait_content_ready()
        await asyncio.wait_for(owner.publication.wait(), 12)
        await ui.step()
        view = owner.conversation
        assert isinstance(view.agent_binding, NoAgentConnection) and not view.submissions.active
        assert owner._initial_prompt is None and view._initial_prompt is None
        assert owner.inputs == {"INITIAL_LOCAL_UI_EVENT": 1}

        editor = view.prompt.prompt_text_area
        editor.text = "DRAFT"
        editor.move_cursor((0, 5))
        editor.insert("Z")
        document, undo = editor.document, editor.history
        view.set_reactive(ConversationSessionBinding.agent_ready, False)
        view._initial_prompt = "NEWEST_PENDING_LOCAL_UI_EVENT"
        owner.publication.clear()
        await app.session_navigation.new(lambda: MainScreen(workspace.project))
        await app.selected_session.wait_content_ready()
        await owner.presentation.evict()
        assert view._initial_prompt is None
        assert owner.presentation.state.initial_prompt == "NEWEST_PENDING_LOCAL_UI_EVENT"
        assert owner.presentation.widget is None

        await ui.select_tab(owner.id)
        await asyncio.wait_for(owner.publication.wait(), 12)
        await ui.step()
        restored = owner.conversation
        assert restored is not view and isinstance(restored.agent_binding, NoAgentConnection)
        assert restored._initial_prompt is None and owner.presentation.state is None
        assert owner.inputs == {"INITIAL_LOCAL_UI_EVENT": 1, "NEWEST_PENDING_LOCAL_UI_EVENT": 1}
        editor = restored.prompt.prompt_text_area
        assert editor.document is document and editor.history is undo
        assert editor.text == "DRAFTZ"
        editor.focus()
        await ui.press("ctrl+z")
        assert editor.text == "DRAFT"

        # The consumed value must stay absent on another eviction.
        await app.session_navigation.new(lambda: MainScreen(workspace.project))
        await app.selected_session.wait_content_ready()
        await owner.presentation.evict()
        assert owner.presentation.state.initial_prompt is None
        await ui.select_tab(owner.id)
        await ui.step()
        assert owner.inputs == {"INITIAL_LOCAL_UI_EVENT": 1, "NEWEST_PENDING_LOCAL_UI_EVENT": 1}
        assert isinstance(owner.conversation.agent_binding, NoAgentConnection) and not owner.conversation.submissions.active
        await app.session_navigation.close(owner.id)
        assert owner.presentation.widget is None and owner.presentation.state is None
        assert owner.id not in app.workspace_sessions.views
        assert ui.failure() is None
