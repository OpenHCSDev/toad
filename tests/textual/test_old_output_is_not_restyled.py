"""Textual-facing: appending output or toggling the sidebar must not make Textual restyle widgets already in the transcript."""

from toad.widgets.agent_response import AgentResponse
from toad.widgets.side_bar import SideBar


async def test_append_and_sidebar_toggle_leave_old_transcript_widgets_unstyled(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        app, _ = ui.textual
        response = AgentResponse("\n\n".join(f"## Heading {i}\n\nA paragraph." for i in range(80)))
        await ui.conversation.post(response)
        await ui.step()
        old = set(response.walk_children(with_self=True))
        original = app.stylesheet.apply
        styled = 0

        def apply(node, *args, **kwargs):
            nonlocal styled
            styled += node in old
            return original(node, *args, **kwargs)

        app.stylesheet.apply = apply
        await response.append_fragment("\n\n## New output\n\nAnother paragraph.")
        await ui.step()
        assert styled == 0, "appending restyled old widgets"
        app.screen.query_one(SideBar).toggle()
        await ui.step()
        assert styled == 0, "toggling the sidebar restyled old widgets"
