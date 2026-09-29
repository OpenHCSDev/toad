"""A real mounted welcome publication cannot consume the next source's input."""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from runtime_fixture import ToadApp
from toad.screens.main import MainScreen
from toad.widgets.markdown_note import MarkdownNote


async def main():
    with TemporaryDirectory(prefix="welcome-source-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            await pilot.pause()
            view = app.selected_session.conversation
            old_source = view.transcript
            entered, release = asyncio.Event(), asyncio.Event()
            original_post = view.post

            async def delayed_post(note):
                # Use actual mounted publication, delaying only completion to
                # expose the ordinary asynchronous source-change boundary.
                result = await original_post(note)
                entered.set()
                await release.wait()
                return result

            view._agent_data = {"identity": "welcome-source-probe", "welcome": "OLD_SOURCE_WELCOME"}
            view.post = delayed_post
            worker = view.watch_agent_ready(True)
            try:
                async with asyncio.timeout(12):
                    await entered.wait()
                    assert view.query(MarkdownNote)
                    await app.new_session_screen(lambda: MainScreen(root))
                    await app.selected_session.wait_content_ready()
                    await pilot.pause()
                    assert app.selected_session.conversation is view
                    assert view.transcript is not old_source
                    # This pending owned input is deliberately not submitted by
                    # the test. A retired callback must neither clear nor post it.
                    view._initial_prompt = "NEXT_SOURCE_OWNED_INPUT"
                    release.set()
                    await worker.wait()
                    await pilot.pause()
                    assert view._initial_prompt == "NEXT_SOURCE_OWNED_INPUT"
                    assert app._exception is None
                    print("INSTALLED_WELCOME_REAL_PUBLICATION_REBIND_RETIRED_CALLBACK_NO_INPUT", flush=True)
            finally:
                release.set()
                view.post = original_post
                view._initial_prompt = None
        print("WELCOME_SOURCE_JOURNEY_EXIT", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
