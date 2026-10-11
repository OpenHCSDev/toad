"""Textual-facing: hiding a message by category is a display change that Textual's stylesheet must not re-match for descendants."""

from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.containers import VerticalGroup
from textual.widgets import Label

from toad.textual_colours import ThemedApp
from toad.widgets.message_filter import ThinkingCategory, CategorizedBlock, all_categories, apply_block_filter


class Block(CategorizedBlock, VerticalGroup):
    @property
    def message_category(self):
        return ThinkingCategory

    def compose(self) -> ComposeResult:
        yield Label("Nested message body", classes="probe")


class FilterApp(ThemedApp, App):
    CSS = ".probe { color: blue; }"

    def compose(self) -> ComposeResult:
        yield Block()


async def test_filter_toggle_does_not_restyle_descendants():
    app = FilterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.screen.query_one(Block)
        child = block.query_one(Label)
        with patch.object(child, "notify_style_update", wraps=child.notify_style_update) as notify:
            apply_block_filter(block, frozenset())
            assert not block.display
            apply_block_filter(block, all_categories())
            assert block.display
            assert notify.call_count == 0, "Display-only filter restyled descendants"


async def test_filter_keeps_display_set_by_the_block_itself():
    app = FilterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.screen.query_one(Block)
        block.styles.display = "none"
        apply_block_filter(block, frozenset())
        apply_block_filter(block, all_categories())
        assert not block.display, "Filtering overwrote authored display intent"


async def test_descendant_css_for_the_hidden_class_still_applies():
    app = FilterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        block = app.screen.query_one(Block)
        child = block.query_one(Label)
        app.stylesheet.add_source(".-category-hidden .probe { color: red; }", read_from=("fixture", "descendant"))
        apply_block_filter(block, frozenset())
        assert child.styles.color.css == "rgb(255,0,0)"
        apply_block_filter(block, all_categories())
        assert child.styles.color.css == "rgb(0,0,255)"
