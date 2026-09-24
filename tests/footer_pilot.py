"""Focus-only binding notifications reuse keys; actual binding changes still render."""

import asyncio
import os
import tempfile
from pathlib import Path

from textual.widgets._footer import FooterKey
from toad.app import ToadApp
from toad.widgets.footer import Footer


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-footer-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            footer = app.screen.query_one(Footer)
            keys = tuple(footer.query(FooterKey))
            assert keys
            app.screen.refresh_bindings()
            await pilot.pause()
            assert tuple(footer.query(FooterKey)) == keys
            app.app_focus = False
            await pilot.pause()
            app.app_focus = True
            await pilot.pause()
            assert tuple(footer.query(FooterKey)) == keys, "Window focus recreated unchanged footer keys"
            footer.show_command_palette = False
            app.screen.refresh_bindings()
            await pilot.pause()
            assert not footer.query(".-command-palette")
            footer.show_command_palette = True
            app.screen.refresh_bindings()
            await pilot.pause()
            assert footer.query(".-command-palette")

            # A requested rebuild can run after focus is lost. Its memo must
            # describe the composed bindings, not the earlier request.
            footer.show_command_palette = False
            with footer._context():
                footer.bindings_changed(app.screen)
            app.app_focus = False
            await pilot.pause()
            app.app_focus = True
            await pilot.pause()
            assert not footer.query(".-command-palette")

            def displayed_keys():
                return tuple((key.key, key.key_display, key.description, key.action,
                              key._disabled, key.tooltip) for key in footer.query(FooterKey))

            retained = displayed_keys()
            with footer._context():
                await footer.recompose()
            await pilot.pause()
            assert displayed_keys() == retained, "Focus restored stale footer bindings"

            # Changed bindings while blurred must still appear on refocus.
            app.app_focus = False
            await pilot.pause()
            footer.show_command_palette = True
            app.screen.refresh_bindings()
            await pilot.pause()
            app.app_focus = True
            await pilot.pause()
            assert footer.query(".-command-palette")
    print("footer: unchanged bindings keep their widgets; changed display rebuilds correctly")


if __name__ == "__main__":
    asyncio.run(main())
