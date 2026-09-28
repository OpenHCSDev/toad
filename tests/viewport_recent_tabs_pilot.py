"""A global warm budget avoids repeat source rebuilds without multiplying per tab."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse


class TwoWarmApp(ToadApp):
    WARM_DOCUMENT_WINDOWS = 2


async def settled(view, pilot):
    async with asyncio.timeout(12):
        while True:
            await pilot.pause(.02)
            viewport = view.window.document_viewport
            if not viewport._running and viewport.visible_bodies_ready:
                return


async def main():
    with TemporaryDirectory(prefix="toad-warm-viewports-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = TwoWarmApp(project_dir=str(root))
        async with app.run_test(size=(100, 34)) as pilot:
            windows, tails, modes = [], [], []
            for index in range(4):
                if index:
                    await app.new_session_screen(app.get_main_screen)
                await pilot.pause()
                view = app.screen.conversation
                docs = [AgentResponse(f"## View {index}, record {n}\n\n" + "source words " * 24)
                        for n in range(16)]
                await view.contents.mount(*docs)
                view.window.anchor()
                await settled(view, pilot)
                assert docs[-1].body_ready
                modes.append(app.current_mode)
                windows.append(view.window)
                tails.append(docs[-1])
            await settled(app.screen.conversation, pilot)
            assert len(app.window_presentation_pool._recent) == 2
            async with asyncio.timeout(5):
                while not tails[0].body_dormant:
                    await pilot.pause(.02)
            assert tails[1].body_ready and tails[2].body_ready
            assert tails[3].body_ready
            await app.switch_mode(modes[1])
            await settled(app.screen.conversation, pilot)
            assert tails[1].body_ready and tails[1] in app.screen._compositor.visible_widgets
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("warm viewports: two recent windows retained, oldest retired, original source visible on revisit")


if __name__ == "__main__":
    asyncio.run(main())
