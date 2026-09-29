"""Installed source-message navigation, resize and original editor custody."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import toad
from textual.widgets._markdown import MarkdownParagraph

from runtime_fixture import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.project_panel import FilePreview


async def main():
    installed = Path(toad.__file__).parent
    assert "site-packages" in str(installed)
    ToadApp.CSS_PATH = installed / "toad.tcss"
    with TemporaryDirectory(dir=os.environ["TMPDIR"], prefix="source-navigation-") as directory:
        project = Path(directory)
        target = project / "navigation-proof.txt"
        target.write_text("SOURCE_NAVIGATION_FILE_PAINT\n")
        os.environ.update(AGENT_COMMS_ROOT=str(project / "wire"),
                          TOAD_TEST_ATTEMPT=f"workspace-source-navigation-{os.getpid()}",
                          XDG_CONFIG_HOME=str(project / "config"),
                          XDG_STATE_HOME=str(project / "state"),
                          XDG_DATA_HOME=str(project / "data"))
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            frame, owner = app.screen, app.selected_session
            conversation = owner.conversation
            editor = conversation.prompt.prompt_text_area
            editor.insert("retained navigation draft")
            editor.history.checkpoint()
            editor.insert(" with undo")
            document, history = editor.document, editor.history
            response = await conversation.post(AgentResponse(f"[Open source file]({target})"))
            async with asyncio.timeout(10):
                while not response.query(MarkdownParagraph):
                    await pilot.pause(.02)
            paragraph = response.query_one(MarkdownParagraph)
            paragraph.scroll_visible(animate=False)
            await pilot.pause()
            print("SOURCE_LINK_READY", flush=True)
            assert await pilot.click(paragraph, offset=(5, 0))
            print("SOURCE_LINK_CLICK_RETURNED", flush=True)
            async with asyncio.timeout(10):
                while not app.screen.query(FilePreview):
                    await pilot.pause(.02)
            preview = app.screen.query_one(FilePreview)
            await asyncio.wait_for(preview.wait_ready(), 10)
            await pilot.pause()
            assert app.screen is frame
            await pilot.resize_terminal(72, 26)
            await pilot.pause()
            painted = "\n".join(strip.text for strip in frame._compositor.render_strips())
            assert "SOURCE_NAVIGATION_FILE_PAINT" in painted
            await app.select_session(owner.id)
            await pilot.pause()
            restored = owner.conversation.prompt.prompt_text_area
            assert restored is editor
            assert restored.document is document and restored.history is history
            restored.undo()
            assert restored.text == "retained navigation draft"
            assert app.screen is frame and app._exception is None
    print("Installed source link/resize/return/teardown and original editor passed")


if __name__ == "__main__":
    asyncio.run(main())
