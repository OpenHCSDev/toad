"""Display-only filtering stays local; authored descendant CSS keeps its semantics."""

import asyncio
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.containers import VerticalGroup
from textual.widgets import Label

from toad.widgets.message_filter import ALL_CATEGORIES, CategorizedBlock, MessageCategory, apply_block_filter


class Block(CategorizedBlock, VerticalGroup):
    @property
    def message_category(self):
        return MessageCategory.THINKING

    def compose(self) -> ComposeResult:
        yield Label("Nested message body", classes="probe")


class FilterApp(App):
    CSS = ".probe { color: blue; }"

    def compose(self) -> ComposeResult:
        yield Block()


async def main():
    app = FilterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.screen.query_one(Block)
        child = block.query_one(Label)
        with patch.object(child, "notify_style_update", wraps=child.notify_style_update) as notify:
            apply_block_filter(block, frozenset())
            assert not block.display
            apply_block_filter(block, ALL_CATEGORIES)
            assert block.display
            assert notify.call_count == 0, "Display-only filter restyled descendants"
        block.styles.display = "none"
        apply_block_filter(block, frozenset())
        apply_block_filter(block, ALL_CATEGORIES)
        assert not block.display, "Filtering overwrote authored display intent"
        block.styles.display = None
        app.stylesheet.add_source(".-category-hidden .probe { color: red; }", read_from=("fixture", "descendant"))
        apply_block_filter(block, frozenset())
        assert child.styles.color.css == "rgb(255,0,0)"
        apply_block_filter(block, ALL_CATEGORIES)
        assert child.styles.color.css == "rgb(0,0,255)"
    print("filter styles: local display changes skip descendants; authored display and descendant CSS preserved")


if __name__ == "__main__":
    asyncio.run(main())
