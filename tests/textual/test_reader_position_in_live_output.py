"""Textual-facing: the history window keeps the tail in view through growth and resize, keeps a reading position, and survives a session switch.

Not carried over from the old script: the count of nested layout passes during paint preparation (the
viewport presentation owner it observed no longer exists; history is line-drawn).
"""

from toad.widgets.agent_response import AgentResponse


async def test_window_follows_growth_and_resize_then_holds_a_reading_position(workspace):
    async with workspace.app(size=(139, 25)) as ui:
        view = ui.conversation
        response = await view.post(AgentResponse("\n\n".join(f"Visible paragraph {i}" for i in range(45))))
        window = view.window
        window.anchor()
        await ui.until(lambda: window.max_scroll_y > 0 and window.follows_tail, why="a scrollable tail")
        window.scroll_y = window.max_scroll_y - 1
        await ui.until(lambda: window.scroll_y == window.max_scroll_y, why="the pending tail gap closed")
        for width, height in ((70, 25), (139, 25), (139, 26), (139, 25)):
            await ui.resize(width, height)
            await response.append_fragment("\n\nGROWTH_MARKER visible live tail after resize.")
            await ui.until(lambda: window.follows_tail and window.scroll_y == window.max_scroll_y,
                           why="the tail followed after growth")
        window.scroll_relative(y=-5, animate=False, immediate=True)
        await ui.step()
        position = window.scroll_y
        await response.append_fragment("\n\nAdditional output while reading.")
        await ui.step()
        assert not window.follows_tail and window.scroll_y == position
        window.scroll_end(animate=False, immediate=True)
        await ui.until_shows("Additional output while reading")


async def test_reader_returns_to_the_same_session_after_a_switch(workspace):
    async with workspace.app(size=(139, 25)) as ui:
        first = ui.selected_tab
        response = await ui.conversation.post(AgentResponse("\n\n".join(f"Visible paragraph {i}" for i in range(45))))
        await response.append_fragment("\n\nTAIL_MARKER at the end.")
        ui.conversation.window.anchor()
        await ui.until_shows("TAIL_MARKER")
        await ui.new_session()
        await ui.select_tab(first)
        await ui.until_shows("TAIL_MARKER")
