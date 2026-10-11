"""Textual-facing: many or long tab labels give the tab strip a one-cell horizontal scrollbar under the underline."""

from toad.widgets.session_tabs import SessionsTabs


async def test_many_open_tabs_scroll_the_strip_horizontally(workspace):
    async with workspace.app(size=(100, 36)) as ui:
        for _ in range(8):
            await ui.new_session()
        tabs = ui.textual[0].screen.query_one(SessionsTabs)
        assert tabs.region.y == 0
        assert tabs.max_scroll_x > 0
        assert tabs.show_horizontal_scrollbar
        assert tabs.scrollbar_size_horizontal == 1
        assert tabs.region.height == 3
        tabs.scroll_to(x=tabs.max_scroll_x, animate=False, immediate=True)
        await ui.step()
        assert tabs.scroll_x == tabs.max_scroll_x
        tabs.horizontal_scrollbar.action_scroll_up()
        await ui.until(lambda: tabs.scroll_x < tabs.max_scroll_x, why="the scrollbar to scroll the strip")
