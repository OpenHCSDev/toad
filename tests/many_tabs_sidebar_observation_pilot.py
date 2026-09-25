"""Global observations should not repeatedly traverse hidden tab sidebars."""

import asyncio
from collections import Counter
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.widgets.message_filter import MessageCategory
from toad.widgets.thread_comms import ThreadCommsSidebar
from toad.widgets.comms_sidebar import CommsSidebar
from textual.widgets import Checkbox


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-many-tabs-observe-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 37)) as pilot:
            await pilot.pause()
            modes = [app.current_mode]
            for _ in range(9):
                modes.append((await app.new_session_screen(app.get_main_screen)).mode_name)
            await pilot.pause()
            active = app.current_mode
            sidebars = {mode: app.get_screen_stack(mode)[0].query_one(ThreadCommsSidebar)
                        for mode in modes}
            assert all(sidebar.is_attached for sidebar in sidebars.values())
            counts = Counter()
            original = ThreadCommsSidebar._sync_filter_control

            def counted(sidebar):
                counts[sidebar.screen.id] += 1
                return original(sidebar)

            with patch.object(ThreadCommsSidebar, "_sync_filter_control", counted):
                for _ in range(40):
                    app.open_tabs_changed.publish(None)
                await pilot.pause()
            assert counts[active] > 0, "The selected tab stopped observing changes"
            assert not any(counts[mode] for mode in modes if mode != active), counts

            core_counts = Counter()
            original_mode = CommsSidebar._mode_changed
            original_present = CommsSidebar._present_snapshot

            def counted_mode(sidebar, *args, **kwargs):
                core_counts[(sidebar.screen.id, "mode")] += 1
                return original_mode(sidebar, *args, **kwargs)

            async def counted_present(sidebar, *args, **kwargs):
                core_counts[(sidebar.screen.id, "present")] += 1
                return await original_present(sidebar, *args, **kwargs)

            with (patch.object(CommsSidebar, "_mode_changed", counted_mode),
                  patch.object(CommsSidebar, "_present_snapshot", counted_present)):
                for _ in range(20):
                    app.session_update_signal.publish((active, app.session_tracker.get_session(active)))
                    app.thread_actions_changed.publish(None)
                    app.mode_change_signal.publish(active)
                await pilot.pause()
            assert core_counts[(active, "mode")] > 0
            assert not any(core_counts[(mode, kind)] for mode in modes if mode != active
                           for kind in ("mode", "present")), core_counts

            old = modes[0]
            view = app.get_screen_stack(old)[0].conversation
            view.visible_categories = frozenset((MessageCategory.THINKING,))
            await asyncio.wait_for(app.switch_mode(old), 3)
            await pilot.pause()
            assert sidebars[old].query_one("#filter-thinking", Checkbox).value
            assert not sidebars[old].query_one("#filter-user", Checkbox).value
            left = app.screen.query_one(CommsSidebar)
            assert left._rendered_mode is not None and left._rendered_mode[0] == old
            assert view.visible_categories == frozenset((MessageCategory.THINKING,))
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print(f"10 mounted tabs, 40 observations: selected sidebar synced {counts[active]} times; hidden sidebars synced 0; routed/session rows caught up on return")


if __name__ == "__main__":
    asyncio.run(main())
