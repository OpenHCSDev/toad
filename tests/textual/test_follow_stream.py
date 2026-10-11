"""Textual-facing: the history window follows live output at the tail, releases while reading, resumes at the tail."""

from toad.widgets.agent_response import AgentResponse


async def test_window_follows_tail_releases_on_scroll_up_and_resumes(workspace):
    async with workspace.app(size=(100, 30)) as ui:
        conversation = ui.conversation
        response = await conversation.post(AgentResponse("\n\n".join(f"Paragraph {i}" for i in range(40))))
        window = conversation.window
        window.anchor(False)
        conversation.refresh_block_cursor()
        assert window.follows_tail, "Returning the block cursor to the composer disabled follow"
        window.anchor()
        await ui.step()
        await response.append_fragment("\n\nNew output at the tail.")
        await ui.step()
        assert window.follows_tail and window.scroll_y == window.max_scroll_y
        window.scroll_relative(y=-8, animate=False, immediate=True)
        await ui.step()
        position = window.scroll_y
        await response.append_fragment("\n\nOutput while reading older text.")
        await ui.step()
        assert not window.follows_tail and window.scroll_y == position
        window.scroll_end(animate=False, immediate=True)
        await ui.step()
        assert window.follows_tail
        for width, height in ((145, 40), (70, 25), (100, 30)):
            await ui.resize(width, height)
            await response.append_fragment("\n\nFurther live output after resize.")
            await ui.step()
            assert window.follows_tail and window.scroll_y == window.max_scroll_y
