"""Style refreshes reuse unchanged fence highlighting and geometry."""

from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import Markdown, Label
from textual.widgets._markdown import MarkdownFence
import textual.widgets._markdown as markdown_module


async def test_unchanged_style_refresh_reuses_fence_highlight_and_label():
    class FenceApp(App):
        def compose(self) -> ComposeResult:
            yield Markdown("```python\nvalue = 123\n```\n")

    app = FenceApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        fence = app.query_one(MarkdownFence)
        label = fence.query_one(Label)
        before = fence._highlighted_code
        with patch.object(markdown_module, "highlight", wraps=markdown_module.highlight) as highlight:
            with patch.object(label, "update", wraps=label.update) as update:
                for _ in range(5):
                    fence.notify_style_update()
                highlight.assert_not_called()
                update.assert_not_called()
        assert fence._highlighted_code is before
        app.theme = "textual-light"
        await pilot.pause()
        assert fence._highlighted_key[-1] is False
        assert fence._highlighted_code is not before
        assert fence._highlighted_code.plain == before.plain


async def test_append_replaces_fence_highlight_context():
    class FenceApp(App):
        def compose(self) -> ComposeResult:
            yield Markdown("```python\nvalue = 1")

    app = FenceApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        markdown = app.query_one(Markdown)
        await markdown.append("23\n```\n")
        await pilot.pause()
        fence = app.query_one(MarkdownFence)
        assert fence.code == "value = 123"
        assert fence._highlighted_key[:2] == (fence.code, fence.lexer)
        with patch.object(markdown_module, "highlight", side_effect=AssertionError("unexpected rehighlight")):
            fence.notify_style_update()
        assert fence.query_one(Label).content.plain == "value = 123"
