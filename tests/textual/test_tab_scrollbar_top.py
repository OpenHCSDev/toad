"""Textual-facing: the tab strip's horizontal scrollbar is drawn above the labels and underline, with matching pointer geometry, as overflow comes and goes."""

from toad.widgets.session_tabs import SessionLabel, SessionsTabs, SessionTabClose, Underline

HEIGHT = 35


async def open_peers(ui, count: int) -> list[str]:
    """Open `count` more sessions with long titles; returns their tab identities."""
    peers = []
    for index in range(count):
        identity = await ui.new_session()
        ui.app.session_tracker.name_session(identity, f"thread-{index}-long-title")
        peers.append(identity)
    await ui.step()
    await ui.pilot.wait_for_scheduled_animations()
    return peers


def underline_is_painted(ui, tabs, underline, x_from=None, x_to=None):
    """The underline's visible row, and whether its highlight bar is painted in it."""
    clip = ui.app.screen._compositor.find_widget(underline).clip
    visible = underline.region.intersection(clip)
    painted = ui.app.screen._compositor.render_strips()[visible.y].crop(
        visible.x if x_from is None else x_from, visible.right if x_to is None else x_to)
    color = underline.get_component_rich_style("underline--bar").color
    return visible, any(segment.style is not None and segment.style.color == color
                        and "━" in segment.text for segment in painted), tuple(painted)


async def test_a_single_tab_shows_no_scrollbar_and_its_underline_is_visible(workspace):
    async with workspace.app(size=(100, HEIGHT)) as ui:
        identity = await ui.new_session()
        await ui.step()
        tabs = ui.app.screen.query_one(SessionsTabs)
        label = tabs.query_one(f"#{identity}", SessionLabel)
        assert not tabs.show_horizontal_scrollbar
        assert label.region.y == tabs.content_region.y + 1
        underline = tabs.query_one(Underline)
        clip = ui.app.screen._compositor.find_widget(underline).clip
        assert underline.region.intersection(clip).height == 1, (
            tabs.region, label.region, underline.region, clip)


async def test_overflowing_tabs_put_the_scrollbar_above_the_labels_and_underline(workspace):
    async with workspace.app(size=(100, HEIGHT)) as ui:
        await open_peers(ui, 5)
        app = ui.app
        tabs = app.screen.query_one(SessionsTabs)
        assert tabs.show_horizontal_scrollbar
        scrollbar = tabs.horizontal_scrollbar
        label = tabs.query_one(f"#{ui.selected_tab}", SessionLabel)
        underline = tabs.query_one(Underline)
        assert scrollbar.region.y == tabs.content_region.y
        assert scrollbar.region.bottom <= label.region.y, (scrollbar.region, label.region)
        assert label.region.bottom <= underline.region.y
        assert label.region.y == scrollbar.region.y + 1
        clip = app.screen._compositor.find_widget(underline).clip
        assert underline.region.intersection(clip).height == 1, (
            tabs.region, label.region, underline.region, clip)
        assert app.screen.get_widget_at(label.region.x + 1, underline.region.y)[0] is underline
        _, highlighted, painted = underline_is_painted(
            ui, tabs, underline, label.region.x + 1, label.region.right - 1)
        assert highlighted, painted


async def test_scrollbar_click_scrolls_the_tabs_and_label_click_selects_without_scrolling_away(workspace):
    async with workspace.app(size=(100, HEIGHT)) as ui:
        owner = ui.selected_tab
        await open_peers(ui, 5)
        app, pilot = ui.textual
        tabs = app.screen.query_one(SessionsTabs)
        scrollbar = tabs.horizontal_scrollbar
        tabs.scroll_to(x=0, animate=False, immediate=True)
        await ui.step()
        before = ui.selected_tab
        assert await pilot.click(scrollbar, offset=(scrollbar.size.width - 2, 0))
        await ui.step()
        await pilot.wait_for_scheduled_animations()
        assert tabs.scroll_x > 0 and ui.selected_tab == before

        tabs.scroll_to(x=0, animate=False, immediate=True)
        await ui.step()
        assert await pilot.click(tabs.query_one(f"#{owner}", SessionLabel))
        await ui.until(lambda: ui.selected_tab == owner, why="the clicked tab to be selected")


async def test_mouse_close_keeps_the_editor_focus_and_keyboard_close_works(workspace):
    async with workspace.app(size=(100, HEIGHT)) as ui:
        owner = ui.selected_tab
        peers = await open_peers(ui, 5)
        app, pilot = ui.textual
        await ui.select_tab(owner)
        tabs = app.screen.query_one(SessionsTabs)
        close = tabs.query_one(f"#close-{peers[0]}", SessionTabClose)
        close.scroll_visible(animate=False)
        await ui.step()
        original_focus = app.screen.focused
        assert await pilot.click(close)
        await ui.until(lambda: app.session_tracker.get_session(peers[0]) is None, why="the clicked tab to close")
        assert ui.selected_tab == owner
        assert app.screen.focused is original_focus

        # Mouse close keeps the editor's focus; keyboard close remains
        # available through the focusable close control and its binding.
        keyboard_close = tabs.query_one(f"#close-{peers[1]}", SessionTabClose)
        keyboard_close.focus(scroll_visible=False)
        await ui.step()
        assert keyboard_close.has_focus
        await ui.press("enter")
        await ui.until(lambda: app.session_tracker.get_session(peers[1]) is None, why="the focused tab to close")
        assert ui.selected_tab == owner


async def test_scrollbar_follows_the_width_of_the_terminal(workspace):
    async with workspace.app(size=(100, HEIGHT)) as ui:
        owner = ui.selected_tab
        await open_peers(ui, 5)
        tabs = ui.app.screen.query_one(SessionsTabs)
        for width in (300, 100):
            await ui.resize(width, HEIGHT)
            label = tabs.query_one(f"#{owner}", SessionLabel)
            if width == 300:
                assert not tabs.show_horizontal_scrollbar
                assert label.region.y == tabs.content_region.y + 1
            else:
                assert tabs.show_horizontal_scrollbar
                assert tabs.horizontal_scrollbar.region.bottom <= label.region.y


async def test_overflow_appearing_on_a_mounted_strip_keeps_the_underline_painted(workspace):
    async with workspace.app(size=(100, HEIGHT)) as ui:
        owner = ui.selected_tab
        await open_peers(ui, 5)
        app = ui.app
        tabs = app.screen.query_one(SessionsTabs)
        for theme in ("ansi-dark", "textual-dark"):
            app.theme = theme
            for long_titles in (False, True, False, True):
                for index, session in enumerate(app.session_tracker.ordered_sessions):
                    title = (f"pr17-standby-liveness-owner-{index} working on active goal"
                             if long_titles else str(index))
                    app.session_tracker.name_session(session.mode_name, title)
                await ui.step()
                await ui.pilot.wait_for_scheduled_animations()
                assert tabs.show_horizontal_scrollbar == long_titles
                label = tabs.query_one(f"#{owner}", SessionLabel)
                underline = tabs.query_one(Underline)
                visible, highlighted, painted = underline_is_painted(ui, tabs, underline)
                assert visible.height == 1, (theme, long_titles, underline.region)
                assert label.region.y == tabs.content_region.y + 1
                assert highlighted, (theme, long_titles, tabs.scroll_offset, underline.region, painted)
