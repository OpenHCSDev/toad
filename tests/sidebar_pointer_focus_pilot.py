"""Pointer toggles preserve editing focus; keyboard toggles still enter the pane."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from runtime_fixture import ToadApp
from toad.widgets.footer import Footer
from toad.widgets.side_bar import SideBar, SideBarToggle


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-sidebar-focus-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(113, 42)) as pilot:
            await pilot.pause()
            prompt = app.screen.conversation.prompt.prompt_text_area
            app.screen.conversation.prompt.text = "retained draft"
            for identity in ("channels-sidebar", "thread-sidebar"):
                bar = app.screen.query_one(f"#{identity}", SideBar)
                toggle = bar.query_one(SideBarToggle)
                prompt.focus()
                await pilot.pause()
                footer = app.screen.query_one(Footer)
                with patch.object(footer, "recompose", wraps=footer.recompose) as recompose:
                    for _ in range(4):
                        before = bar.collapsed
                        assert await pilot.click(toggle)
                        await pilot.pause()
                        assert bar.collapsed != before
                        assert app.focused is prompt, (identity, type(app.focused).__name__)
                        assert app.screen.conversation.prompt.text == "retained draft"
                    assert recompose.call_count == 0
                # Focus remains available for users reaching the handle by Tab.
                if not bar.collapsed:
                    bar.toggle()
                    await pilot.pause()
                toggle.focus(scroll_visible=False)
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert not bar.collapsed
                title = bar.query_one("SideBarCollapsible CollapsibleTitle")
                assert app.focused is title
                # Closing while focus is inside the pane returns it to input.
                assert await pilot.click(toggle)
                await pilot.pause()
                assert bar.collapsed and app.focused is prompt
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("sidebar pointer focus: no intermediate handle/title focus or footer rebuild; keyboard entry, collapse and draft preserved")


if __name__ == "__main__":
    asyncio.run(main())
