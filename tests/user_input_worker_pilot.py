"""User-authored Markdown shares the same CPU renderer as assistant content."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from textual.widgets._markdown import MarkdownFence
import textual.widgets._markdown as markdown_module

from runtime_fixture import ToadApp
from toad.widgets.user_input import UserInput
from toad.widgets.prepared_markdown import PreparedConversationMarkdown


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-user-render-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        source = "# User example\n\n```python\n" + "value = calculate(123)\n" * 600 + "```\n"
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 38)) as pilot:
            await pilot.pause()
            with patch.object(markdown_module, "highlight", side_effect=AssertionError("User fence highlighted on UI thread")):
                message = UserInput(source)
                await app.screen.conversation.contents.mount(message)
                async with asyncio.timeout(15):
                    while not message.query(MarkdownFence):
                        if app._exception is not None:
                            raise app._exception
                        await pilot.pause(.02)
                await pilot.pause()
                assert message.query_one("#content", PreparedConversationMarkdown).source == source
                fence = message.query_one(MarkdownFence)
                assert fence._highlighted_code.plain == ("value = calculate(123)\n" * 600).rstrip()
                assert fence._highlighted_code.spans
                assert message.get_block_content("clipboard") == source
                assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("user Markdown: shared-worker syntax, native fence styling, source/copy retained")


if __name__ == "__main__":
    asyncio.run(main())
