"""Sidebar navigation survives switching between independently mounted views."""
from runtime_fixture import coordination_update

import argparse
import asyncio
import os
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import wire
from agent_comms.threads import Thread
from comms_boundary_fixture import coordination_fact
from runtime_fixture import ToadApp

from toad.screens.main import MainScreen
from toad.session_tracker import SidebarSelection
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar


class FrameApp(ToadApp):
    CSS_PATH = Path(__file__).resolve().parents[1] / "src/toad/toad.tcss"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.panel_frames = None

    def panel_text(self, screen):
        sidebar = screen.query_one_optional(CommsSidebar)
        if sidebar is None:
            return ()
        region = sidebar.navigation.scroll_containers[0].content_region
        return tuple(
            (
                strip.text[region.x : region.right]
                for strip in screen._compositor.render_strips()[
                    region.y : region.bottom
                ]
            )
        )

    def _display(self, screen, renderable):
        if (
            self.panel_frames is not None
            and renderable is not None
            and (not self._batch_count)
            and (screen is self.screen)
            and (screen.query_one_optional(CommsSidebar) is not None)
        ):
            sidebar = screen.query_one(CommsSidebar)
            self.panel_frames.append(
                (
                    self.current_mode,
                    sidebar.navigation.ready.is_set(),
                    self.panel_text(screen),
                )
            )
        return super()._display(screen, renderable)


async def main(*, finish_before_layout=False):
    original_after_refresh = CommsSidebar.call_after_refresh
    completion_attempts = []

    def before_layout(sidebar, callback, *args, **kwargs):
        if callback == sidebar._finish_navigation:
            if not sidebar.navigation.ready.is_set():
                completion_attempts.append(
                    (
                        sidebar.display,
                        sidebar.navigation.channel_scroll_y,
                        sidebar.navigation.scroll_containers[0].max_scroll_y,
                    )
                )
            callback(*args, **kwargs)
            assert not sidebar.navigation.ready.is_set() or sidebar.display
            return True
        return original_after_refresh(sidebar, callback, *args, **kwargs)

    completion_order = (
        patch.object(CommsSidebar, "call_after_refresh", before_layout)
        if finish_before_layout
        else nullcontext()
    )
    with (
        completion_order,
        tempfile.TemporaryDirectory(prefix="toad-sidebar-state-") as directory,
    ):
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        comms = wire(root / "wire")
        comms.registry.declare(
            Thread(
                "worker",
                frozenset({"experiment", *(f"channel-{i:02}" for i in range(30))}),
                str(root),
                process_identity=ProcessIdentity.capture(os.getpid()),
            )
        )
        for index in range(30):
            comms.channels.create_tag(f"channel-{index:02}")
        app = FrameApp(project_dir=str(root))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            owner = app.selected_mode
            worker = await app.session_navigation.new(lambda: MainScreen(root, agent_session_id="worker"))
            await app.screen.on_coordination_update(coordination_update(str(comms.root), 'worker'))
            await app.select_session(owner)
            await pilot.pause()
            sidebar = app.screen.query_one(CommsSidebar)

            def group(view, name):
                return next(
                    (
                        item
                        for item in view.query(ChannelGroup)
                        if item.row.target_name == name
                    )
                )

            async def settled(view):
                async with asyncio.timeout(5):
                    await view.navigation.ready.wait()
                await pilot.pause()

            group(sidebar, "#any").toggle_members()
            selected = group(sidebar, "#channel-28")
            selected.toggle_members()
            await pilot.pause()
            selected.row.scroll_visible(animate=False)
            selected.row.focus(scroll_visible=False)
            await pilot.pause()
            await pilot.wait_for_scheduled_animations()
            expected_scroll = tuple(
                (widget.scroll_y for widget in sidebar.navigation.scroll_containers)
            )
            assert max(expected_scroll) > 0, [
                (
                    type(widget).__name__,
                    widget.size,
                    widget.virtual_size,
                    widget.scroll_y,
                    widget.max_scroll_y,
                )
                for widget in (sidebar, *sidebar.ancestors)
                if hasattr(widget, "virtual_size")
            ]
            expected_frame = app.panel_text(app.screen)
            app.panel_frames = []
            selected.row.action_open_selected()
            await pilot.pause()
            channel_mode = app.selected_mode
            assert channel_mode != owner
            current = app.screen.query_one(CommsSidebar)
            await settled(current)
            assert app.panel_frames and any(
                (mode == channel_mode and ready for mode, ready, _ in app.panel_frames)
            )
            assert all(
                (
                    frame == expected_frame
                    for _, ready, frame in app.panel_frames
                    if ready
                )
            ), app.panel_frames
            app.panel_frames = None
            assert group(current, "#channel-28").expanded
            assert not group(current, "#any").expanded
            actual_scroll = tuple(
                (widget.scroll_y for widget in current.scroll_containers)
            )
            assert actual_scroll == expected_scroll, (
                actual_scroll,
                expected_scroll,
                app.sidebar_state,
                [
                    (widget.scroll_y, widget.max_scroll_y)
                    for widget in current.scroll_containers
                ],
            )
            assert app.sidebar_state.selected == SidebarSelection(
                "#channel-28", "#channel-28"
            )
            group(current, "#channel-28").toggle_members()
            await pilot.pause()
            await pilot.wait_for_scheduled_animations()
            expected_scroll = tuple(
                (widget.scroll_y for widget in current.scroll_containers)
            )
            await app.select_session(owner)
            await pilot.pause()
            await settled(sidebar)
            assert not group(sidebar, "#channel-28").expanded
            assert not group(sidebar, "#any").expanded
            actual_scroll = tuple(
                (widget.scroll_y for widget in sidebar.navigation.scroll_containers)
            )
            assert actual_scroll == expected_scroll, (actual_scroll, expected_scroll)
            assert app.sidebar_state.selected == SidebarSelection(
                "#channel-28", "#channel-28"
            )
            nested = group(sidebar, "#channel-28")
            nested.toggle_members()
            await pilot.pause()
            member = nested._members["worker"]
            member.scroll_visible(animate=False)
            member.focus(scroll_visible=False)
            await pilot.pause()
            await pilot.wait_for_scheduled_animations()
            expected_scroll = tuple(
                (widget.scroll_y for widget in sidebar.navigation.scroll_containers)
            )
            member.action_open_selected()
            assert member.has_class("-selected")
            assert (
                sum((row.has_class("-selected") for row in sidebar._ordered_rows()))
                == 1
            )
            expected_frame = app.panel_text(app.screen)
            app.panel_frames = []
            async with asyncio.timeout(5):
                while app.selected_mode != worker.mode_name or not any(
                    (
                        mode == worker.mode_name and ready
                        for mode, ready, _ in app.panel_frames
                    )
                ):
                    await pilot.pause(0.02)
            current = app.screen.query_one(CommsSidebar)
            await settled(current)
            assert app.panel_frames and any(
                (
                    mode == worker.mode_name and ready
                    for mode, ready, _ in app.panel_frames
                )
            )
            assert all(
                (
                    frame == expected_frame
                    for _, ready, frame in app.panel_frames
                    if ready
                )
            ), app.panel_frames
            app.panel_frames = None
            assert app.selected_mode == worker.mode_name
            assert group(current, "#channel-28").expanded
            assert not group(current, "#any").expanded
            assert app.sidebar_state.selected == SidebarSelection(
                "#channel-28", "worker"
            )
            member = group(current, "#channel-28")._members["worker"]
            assert member.current
            assert member.has_class("-selected")
            assert (
                sum((row.has_class("-selected") for row in current._ordered_rows()))
                == 1
            )
            await pilot.hover(member)
            assert "hover" in member.pseudo_classes and (not member.has_focus), (
                member.region,
                member.pseudo_classes,
                member.has_focus,
                app.get_widget_at(member.region.x, member.region.y),
                current.scroll_containers[0].region,
            )
            await pilot.hover(app.selected_session.conversation.prompt)
            assert "hover" not in member.pseudo_classes and member.current
            assert (
                tuple((widget.scroll_y for widget in current.scroll_containers))
                == expected_scroll
            )
            if finish_before_layout:
                assert any(
                    (
                        not visible and saved > 0
                        for visible, saved, _ in completion_attempts
                    )
                )
                assert any(
                    (
                        visible and saved > maximum
                        for visible, saved, maximum in completion_attempts
                    )
                ), completion_attempts
        await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "sidebar navigation: expansion, scroll, and one remembered selection survive view changes"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--finish-before-layout", action="store_true")
    asyncio.run(main(finish_before_layout=parser.parse_args().finish_before_layout))
