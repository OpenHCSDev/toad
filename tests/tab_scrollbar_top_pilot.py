"""The native tab scrollbar sits above labels with matching pointer geometry."""

import asyncio
import os
import tempfile
from pathlib import Path

from runtime_fixture import ToadApp

from toad.widgets.session_tabs import (
    SessionLabel,
    SessionsTabs,
    SessionTabClose,
    Underline,
)


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-top-tab-scroll-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            owner = app.current_mode
            peers = []
            for index in range(5):
                details = await app.new_session_screen(app.get_main_screen)
                if index == 0:
                    await pilot.pause()
                    initial_tabs = app.screen.query_one(SessionsTabs)
                    initial_label = initial_tabs.query_one(f"#{details.mode_name}", SessionLabel)
                    assert not initial_tabs.show_horizontal_scrollbar
                    assert initial_label.region.y == initial_tabs.content_region.y + 1
                    initial_underline = initial_tabs.query_one(Underline)
                    initial_clip = app.screen._compositor.find_widget(initial_underline).clip
                    assert initial_underline.region.intersection(initial_clip).height == 1, (
                        initial_tabs.region, initial_label.region, initial_underline.region, initial_clip,
                    )
                app.session_tracker.update_session(details.mode_name, title=f"thread-{index}-long-title")
                peers.append(details.mode_name)
            await pilot.pause()
            await pilot.wait_for_scheduled_animations()
            tabs = app.screen.query_one(SessionsTabs)
            assert tabs.show_horizontal_scrollbar
            scrollbar = tabs.horizontal_scrollbar
            label = tabs.query_one(f"#{app.current_mode}", SessionLabel)
            underline = tabs.query_one(Underline)
            assert scrollbar.region.y == tabs.content_region.y
            assert scrollbar.region.bottom <= label.region.y, (scrollbar.region, label.region)
            assert label.region.bottom <= underline.region.y
            assert label.region.y == scrollbar.region.y + 1
            underline_clip = app.screen._compositor.find_widget(underline).clip
            assert underline.region.intersection(underline_clip).height == 1, (
                tabs.region, label.region, underline.region, underline_clip,
            )
            assert app.screen.get_widget_at(label.region.x + 1, underline.region.y)[0] is underline
            painted = app.screen._compositor.render_strips()[underline.region.y].crop(
                label.region.x + 1, label.region.right - 1
            )
            highlight_color = underline.get_component_rich_style("underline--bar").color
            assert any(segment.style is not None and segment.style.color == highlight_color
                       and "━" in segment.text for segment in painted), tuple(painted)

            tabs.scroll_to(x=0, animate=False, immediate=True)
            await pilot.pause()
            before = app.current_mode
            assert await pilot.click(scrollbar, offset=(scrollbar.size.width - 2, 0))
            await pilot.pause()
            await pilot.wait_for_scheduled_animations()
            assert tabs.scroll_x > 0 and app.current_mode == before

            tabs.scroll_to(x=0, animate=False, immediate=True)
            await pilot.pause()
            assert await pilot.click(tabs.query_one(f"#{owner}", SessionLabel))
            await pilot.pause()
            assert app.current_mode == owner
            tabs = app.screen.query_one(SessionsTabs)
            close = tabs.query_one(f"#close-{peers[0]}", SessionTabClose)
            close.scroll_visible(animate=False)
            await pilot.pause()
            assert await pilot.click(close)
            await pilot.pause()
            assert app.session_tracker.get_session(peers[0]) is None
            assert app.current_mode == owner

            for width in (300, 100):
                await pilot.resize_terminal(width, 35)
                await pilot.pause()
                label = tabs.query_one(f"#{owner}", SessionLabel)
                if width == 300:
                    assert not tabs.show_horizontal_scrollbar
                    assert label.region.y == tabs.content_region.y + 1
                else:
                    assert tabs.show_horizontal_scrollbar
                    assert tabs.horizontal_scrollbar.region.bottom <= label.region.y

            # Exercise overflow appearing on this already-mounted strip, rather
            # than only opening a fresh screen that already has many tabs.
            for theme in ("ansi-dark", "textual-dark"):
                app.theme = theme
                for long_titles in (False, True, False, True):
                    for index, session in enumerate(app.session_tracker.ordered_sessions):
                        title = (f"pr17-standby-liveness-owner-{index} working on active goal"
                                 if long_titles else str(index))
                        app.session_tracker.update_session(session.mode_name, title=title)
                    await pilot.pause()
                    await pilot.wait_for_scheduled_animations()
                    assert tabs.show_horizontal_scrollbar == long_titles
                    label = tabs.query_one(f"#{owner}", SessionLabel)
                    underline = tabs.query_one(Underline)
                    clip = app.screen._compositor.find_widget(underline).clip
                    visible = underline.region.intersection(clip)
                    assert visible.height == 1, (theme, long_titles, underline.region, clip)
                    assert label.region.y == tabs.content_region.y + 1
                    painted = app.screen._compositor.render_strips()[visible.y].crop(visible.x, visible.right)
                    color = underline.get_component_rich_style("underline--bar").color
                    assert any(segment.style is not None and segment.style.color == color
                               and "━" in segment.text for segment in painted), (
                        theme, long_titles, tabs.scroll_offset, underline.region, tuple(painted),
                    )
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("tabs: native scrollbar above labels, centered row, pointer scroll/select/close, overflow resize")


if __name__ == "__main__":
    asyncio.run(main())
