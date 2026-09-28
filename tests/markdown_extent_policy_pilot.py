"""Compare content-derived Markdown layout with the native feedback policy."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widget import Widget

from toad.widgets.prepared_markdown import PreparedConversationMarkdown


class NativeFeedbackMarkdown(PreparedConversationMarkdown):
    def _measured_virtual_size_requires_layout(self) -> bool:
        return Widget._measured_virtual_size_requires_layout(self)


class Pair(Screen):
    def _use_viewport_layout(self) -> bool:
        return True

    def compose(self):
        with Horizontal():
            yield PreparedConversationMarkdown(id="derived")
            yield NativeFeedbackMarkdown(id="native")


def geometry(markdown):
    origin = markdown.region.offset
    return [(type(child).__name__, child.region.translate(-origin), child.virtual_size)
            for child in markdown.walk_children(Widget)]


async def main():
    with TemporaryDirectory(prefix="toad-markdown-extent-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(140, 45)) as pilot:
            await app.push_screen(Pair())
            await pilot.pause()
            derived = app.screen.query_one("#derived", PreparedConversationMarkdown)
            native = app.screen.query_one("#native", NativeFeedbackMarkdown)
            for markdown in (derived, native):
                markdown.styles.width = "1fr"
            source = "## Header\n\n" + "Wrapped words and **styling**. " * 35 + "\n\n```python\n" + "x = '" + "wide" * 55 + "'\n```\n\nEnd marker."
            for width in (140, 90, 120, 140):
                await pilot.resize_terminal(width, 45)
                for markdown in (derived, native):
                    await markdown.update(source)
                await pilot.pause()
                assert derived.region.size == native.region.size
                assert derived.virtual_size == native.virtual_size
                assert geometry(derived) == geometry(native)
                assert (derived.show_horizontal_scrollbar, derived.show_vertical_scrollbar) == (
                    native.show_horizontal_scrollbar, native.show_vertical_scrollbar)
                source += "\n\nAppended paragraph. " * 3
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("Markdown extent: native geometry, virtual extents and scrollbar parity across resize/content updates")


if __name__ == "__main__":
    asyncio.run(main())
