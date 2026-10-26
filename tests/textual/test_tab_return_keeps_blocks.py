"""Textual-facing: returning to a session tab shows the same conversation widget, the same response block and children, and the typed draft.

Not carried over from the old script: identity of per-paragraph strip caches, and invalidation of those
caches by new content or resize (agent text is line-drawn now; the paragraph widgets do not exist).
"""

from toad.widgets.agent_response import AgentResponse


async def test_returning_to_a_tab_keeps_its_conversation_blocks_and_draft(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        first = ui.selected_tab
        view = ui.conversation
        response = AgentResponse("## Retained native paint\n\n" + "\n\n".join(
            f"Paragraph {i}: ordinary Markdown retains terminal output." for i in range(4)))
        await view.contents.mount(response)
        await ui.until_shows("Retained native paint")
        children = tuple(response.walk_children())
        await ui.write_draft("warm")
        await ui.new_session()
        await ui.select_tab(first)
        assert ui.conversation is view
        assert tuple(response.walk_children()) == children
        assert ui.draft() == "warm"
        await ui.until_shows("Retained native paint")


async def test_evicted_saved_tab_restores_before_its_first_published_frame(workspace):
    import asyncio
    from dataclasses import replace

    from agent_comms.session_file import RegistrySessionLocation
    from support.journals import assistant_entry, write_journal

    saved = workspace.thread('saved-return')
    journal = write_journal(workspace.project / 'saved-return.jsonl',
        assistant_entry('SAVED_RETURN_BODY', id='saved-answer'))
    workspace.comms.registry.declare(replace(saved, session_file=
        RegistrySessionLocation.from_path(journal, workspace.comms.root)))

    async with workspace.app(size=(110, 35), resume='saved-return') as ui:
        app, _pilot = ui.textual
        first, owner = ui.selected_tab, app.selected_session
        await ui.until_shows('SAVED_RETURN_BODY')
        await ui.write_draft('retained draft')
        editor = ui.conversation.prompt.prompt_text_area
        document, undo = editor.document, editor.history
        old_view = ui.conversation
        other = await ui.new_session()
        await owner.presentation.evict()
        assert owner.presentation.widget is None
        assert owner.presentation.transcript.documents

        # This is the live failure: the rebuilt contents start at width zero,
        # with a saved document to restore while navigation withholds frames.
        await asyncio.wait_for(ui.select_tab(first), timeout=12)
        await ui.until_shows('SAVED_RETURN_BODY')
        assert ui.conversation is not old_view
        assert ui.conversation.contents.line_width > 0
        editor = ui.conversation.prompt.prompt_text_area
        assert editor.document is document and editor.history is undo
        assert ui.draft() == 'retained draft'
        await ui.type('Z')
        assert ui.draft() == 'retained draftZ'

        await asyncio.wait_for(ui.select_tab(other), timeout=12)
        await asyncio.wait_for(ui.select_tab(first), timeout=12)
        await ui.until_shows('SAVED_RETURN_BODY')
        assert ui.draft() == 'retained draftZ'
