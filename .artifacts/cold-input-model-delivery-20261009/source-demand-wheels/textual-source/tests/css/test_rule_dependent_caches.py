"""New unrelated widget CSS must not discard already valid style work."""

from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.color import Color
from textual.css.model import RuleSet
from textual.css.stylesheet import Stylesheet
from textual.dom import DOMNode
from textual.widgets import Static


def test_unrelated_source_keeps_match_cache_but_relevant_source_invalidates():
    sheet = Stylesheet()
    sheet.add_source(".item { color: red; }", read_from=("base", ""))
    node = DOMNode(classes="item")
    sheet.apply(node)
    sheet.add_source(".unrelated { color: blue; }", read_from=("new-widget", ""))
    with patch.object(RuleSet, "check", autospec=True, side_effect=RuleSet.check) as matching:
        sheet.apply(node)
        matching.assert_not_called()
    assert node.styles.color == Color.parse("red")
    sheet.add_source(".item { color: blue; }", read_from=("override", ""))
    sheet.apply(node)
    assert node.styles.color == Color.parse("blue")


def test_source_order_remains_part_of_cache_identity():
    sheet = Stylesheet()
    sheet.add_source(".item { color: red; }", read_from=("first", ""))
    sheet.add_source(".item { color: blue; }", read_from=("second", ""))
    node = DOMNode(classes="item")
    sheet.apply(node)
    assert node.styles.color == Color.parse("blue")
    first = sheet.source.pop(("first", ""))
    sheet.source[("first", "")] = first
    sheet.parse()
    sheet.apply(node)
    assert node.styles.color == Color.parse("red")


async def test_component_keeps_its_style_node_after_unrelated_css_registration():
    class Badge(Static):
        COMPONENT_CLASSES = {"badge--ink"}

    class BadgeApp(App):
        CSS = "Badge > .badge--ink { color: red; }"

        def compose(self) -> ComposeResult:
            yield Badge("badge")

    app = BadgeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        badge = app.query_one(Badge)
        original = badge._component_styles["badge--ink"]
        app.stylesheet.add_source(".some-other-widget { color: blue; }", read_from=("new-widget", ""))
        app.stylesheet.update(app.screen)
        assert badge._component_styles["badge--ink"] is original
        app.stylesheet.add_source("Badge > .badge--ink { color: green; }", read_from=("changed", ""))
        app.stylesheet.update(app.screen)
        assert badge._component_styles["badge--ink"] is not original
        assert badge.get_component_styles("badge--ink").color == Color.parse("green")


def test_variables_and_source_removal_cannot_reuse_old_rule_results():
    sheet = Stylesheet(variables={"shade": "red"})
    sheet.add_source(".item { color: $shade; }", read_from=("base", ""))
    sheet.add_source(".item { color: green; }", read_from=("override", ""))
    node = DOMNode(classes="item")
    sheet.apply(node)
    assert node.styles.color == Color.parse("green")
    sheet.source.pop(("override", ""))
    sheet.parse()
    sheet.apply(node)
    assert node.styles.color == Color.parse("red")
    sheet.set_variables({"shade": "blue"})
    sheet.reparse()
    sheet.apply(node)
    assert node.styles.color == Color.parse("blue")
