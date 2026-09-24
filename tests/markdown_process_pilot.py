"""Large Markdown parsing/fence syntax uses workers with native token/render parity."""

import asyncio
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from runtime_fixture import ToadApp
from textual.widgets._markdown import MarkdownFence
import textual.widgets._markdown as markdown_module
from toad.conversation_markdown import ConversationMarkdown, _ThreadLocalPathParser
from toad.markdown_preparation import prepare_markdown
from toad.widgets.agent_response import AgentResponse


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-markdown-process-") as directory:
        root = Path(directory)
        (root / "example.py").write_text("print('example')\n")
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        source = ("# Header\n\nSee `example.py` and [source](example.py).\n\n"
                  + "Paragraph with **bold**, `inline`, and café 界.\n\n" * 30
                  + "```python\n" + "value = 123\n" * 80 + "```\n")
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            expected = _ThreadLocalPathParser(root.resolve()).parse(source)
            prepared = await app.render_processes.run(prepare_markdown, source, str(root.resolve()),
                                                       app.native_ansi_color, app.current_theme.dark)
            assert [token.as_dict() for token in prepared.tokens] == [token.as_dict() for token in expected]
            response = AgentResponse(paginate=False)
            await app.screen.conversation.post(response)
            await pilot.pause()
            # Calls in worker processes import their own highlighter; parent
            # calls would fail, including fence construction/style notification.
            with patch.object(markdown_module, "highlight", side_effect=AssertionError("UI fence highlighting")):
                await response.update(source)
                await pilot.pause()
                fence = response.query_one(MarkdownFence)
                assert fence._highlighted_code.plain == ("value = 123\n" * 80).rstrip()
                assert fence._highlighted_code.spans
                app.stylesheet.update(response)
                await pilot.pause()
            reference = ConversationMarkdown()
            await app.screen.conversation.post(reference)
            await reference.update(source)
            await pilot.pause()
            native = reference.query_one(MarkdownFence)
            assert fence._highlighted_code == native._highlighted_code
            assert fence._highlighted_code.spans == native._highlighted_code.spans
            assert response.table_of_contents[0][:2] == reference.table_of_contents[0][:2]

            # Streaming partial fences, including small initial chunks.
            with patch.object(markdown_module, "highlight", side_effect=AssertionError("UI streaming highlight")):
                await response.update("```python\nvalue = ")
                await response.append("456\n```\n")
                await pilot.pause()
                assert response.query_one(MarkdownFence).code == "value = 456"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("Markdown process: canonical file links/tokens, code styling, table of contents, streamed fence updates")


if __name__ == "__main__":
    asyncio.run(main())
