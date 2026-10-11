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
