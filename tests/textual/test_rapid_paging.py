"""Textual-facing: PageDown and End through a long window reach the painted tail on every frame, with the draft and its undo untouched.

Not carried over from the old script: per-message body readiness, dormant bodies and warm-body counts
(history is line-drawn; there are no per-message bodies).
"""

from toad.widgets.agent_response import AgentResponse


async def test_paging_down_and_end_reach_the_painted_tail_and_keep_the_draft(workspace):
    async with workspace.app(size=(100, 34)) as ui:
        app, _pilot = ui.textual
        view = ui.conversation
        editor = view.prompt.prompt_text_area
        editor.insert("retained rapid-scroll draft")
        editor.history.checkpoint()
        editor.insert(" with undo")
        document, edit_history = editor.document, editor.history
        docs = [AgentResponse(f"## Record {index}\n\n" + "measured source text " * 25) for index in range(48)]
        docs[-1] = AgentResponse("## LAST SOURCE\n\n" + "last record " * 15 + "\n\nTAIL-RECORD-END")
        await view.contents.mount(*docs)
        window = view.window
        window.anchor()
        await ui.until(lambda: window.max_scroll_y > 100, why="a long window")
        for _round in range(3):
            window.release_anchor()
            window.scroll_to(y=0, animate=False, immediate=True)
            await ui.step()
            for _ in range(18):
                await ui.press("pagedown")
            await ui.press("end")
            await ui.until(lambda: window.follows_tail and window.scroll_y == window.max_scroll_y,
                           why="End to reach the tail")
            await ui.until_shows("TAIL-RECORD-END")
        for index in range(40, -1, -4):
            window.scroll_to_widget(docs[index], animate=False, immediate=True)
            await ui.step()
        frames = []
        display = app._display

        def record(screen, renderable):
            if renderable is not None and not app._batch_count and screen is app.screen:
                frames.append((window.follows_tail, window.scroll_y, window.max_scroll_y))
            return display(screen, renderable)

        app._display = record
        window.focus()
        await ui.press("end")
        await ui.until(lambda: window.follows_tail and window.scroll_y == window.max_scroll_y,
                       why="End from far above to reach the tail")
        app._display = display
        assert frames and all(y <= maximum for _, y, maximum in frames), frames
        await ui.until_shows("TAIL-RECORD-END")
        assert editor.document is document and editor.history is edit_history
        editor.undo()
        assert editor.text == "retained rapid-scroll draft"
