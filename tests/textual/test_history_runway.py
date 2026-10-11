"""Textual-facing: the history window sizes its lookahead from a setting and draws content on every frame of held paging.

Not carried over from the old script: ready runway rows of per-message bodies, warm widget counts and
visible-body readiness (history is line-drawn; there are no per-message bodies).
"""

from toad.widgets.agent_response import AgentResponse


async def long_window(ui):
    view = ui.conversation
    await view.contents.mount(*(AgentResponse(f"## Native runway {i}\n\n" + "\n\n".join(
        f"Paragraph {j} has actual native Markdown geometry." for j in range(4))) for i in range(48)))
    await ui.until(lambda: view.window.max_scroll_y > 200, why="a long window")
    return view.window


async def test_buffer_viewport_setting_sets_the_lookahead_and_can_be_restored(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        app, _pilot = ui.textual
        window = await long_window(ui)
        rows = window.size.height
        assert window.lookahead.travel_rows == 0
        assert window.lookahead.ahead_rows(rows) >= window.presentation_budget.runway_rows(rows)
        app.settings.ui.history_buffer_viewports = 1
        await ui.until(lambda: window.presentation_budget.buffer_viewports == 1, why="the setting reaching the window")
        assert window.lookahead.ahead_rows(rows) == rows
        app.settings.ui.history_buffer_viewports = 3
        await ui.until(lambda: window.presentation_budget.buffer_viewports == 3, why="the setting restored")
        assert window.lookahead.ahead_rows(rows) == 3 * rows


async def test_held_paging_never_draws_a_blank_message_area_and_end_follows_the_tail(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        app, _pilot = ui.textual
        window = await long_window(ui)
        window.release_anchor()
        window.scroll_to(y=window.max_scroll_y / 2, animate=False, immediate=True)
        await ui.step()
        frames = []
        display = app._display

        def record(screen, renderable):
            if renderable is not None and not app._batch_count and screen is app.screen:
                region = window.scrollable_content_region
                text = "".join("".join(strip.crop(region.x, region.right).text.split())
                               for strip in screen._compositor.render_strips()[region.y:region.bottom])
                frames.append(bool(text))
            return display(screen, renderable)

        app._display = record
        try:
            window.focus(scroll_visible=False)
            for key in ("pageup", "pagedown", "pageup"):
                for _ in range(12):
                    await ui.press(key)
            await ui.press("end")
            await ui.until(lambda: window.follows_tail and window.scroll_y == window.max_scroll_y,
                           why="End to follow the tail")
        finally:
            app._display = display
        assert frames and all(frames), f"{frames.count(False)} of {len(frames)} frames had an empty message area"
