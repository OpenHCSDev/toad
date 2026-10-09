"""Reapplying static CSS should not trigger unchanged descriptor side effects."""

from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.color import Color
from textual.containers import VerticalScroll
from textual.css.stylesheet import Stylesheet
from textual.widgets import Static


async def test_identical_rules_keep_paint_and_preparation():
    class ScrollApp(App):
        CSS = "VerticalScroll { height: 4; color: red; } Static { height: 1; }"

        def compose(self) -> ComposeResult:
            with VerticalScroll():
                for index in range(10):
                    yield Static(str(index))

    app = ScrollApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        scroller = app.query_one(VerticalScroll)
        child = app.query_one(Static)
        assert scroller.show_vertical_scrollbar
        rules = scroller.styles.base.get_rules()
        with patch.object(scroller.vertical_scrollbar, "refresh", wraps=scroller.vertical_scrollbar.refresh) as repaint:
            with patch.object(scroller, "notify_style_update", wraps=scroller.notify_style_update) as notify:
                Stylesheet.replace_rules(scroller, rules.copy())
                repaint.assert_not_called()
                notify.assert_not_called()

        changed = dict(rules, color=Color.parse("blue"), scrollbar_color=Color.parse("green"))
        with patch.object(scroller.vertical_scrollbar, "refresh", wraps=scroller.vertical_scrollbar.refresh) as repaint:
            with patch.object(scroller, "_style_rules_updated", wraps=scroller._style_rules_updated) as publish:
                Stylesheet.replace_rules(scroller, changed)
                assert publish.call_count == 1
            assert repaint.called
        await pilot.pause()
        assert scroller.styles.scrollbar_color == Color.parse("green")
        assert child.rich_style.color.get_truecolor() == (0, 0, 255)

        # Clearing a declaration must still restore inheritance and defaults.
        changed.pop("color")
        Stylesheet.replace_rules(scroller, changed)
        assert not scroller.styles.base.has_rule("color")
        Stylesheet.replace_rules(scroller, rules)
        await pilot.pause()
        assert child.rich_style.color.get_truecolor() == (255, 0, 0)


def test_rule_cohort_validates_before_live_publication():
    from textual.css.errors import StyleValueError
    from textual.css.styles import Styles
    from textual.dom import DOMNode
    import pytest

    node = DOMNode()
    styles = Styles(node)
    styles.color = "red"
    before = styles.get_rules()
    revision = node._subtree_style_revision
    with pytest.raises(StyleValueError):
        styles.replace_rules(dict(before, color=Color.parse("blue"), display="invalid"))
    assert styles.get_rules() == before
    assert node._subtree_style_revision == revision

    with patch.object(node, "_style_rules_updated", wraps=node._style_rules_updated) as publish:
        styles.replace_rules(dict(before, color=Color.parse("blue"), opacity=0.5))
        assert publish.call_count == 1
        assert styles.color == Color.parse("blue")
        assert styles.opacity == 0.5
    # Authored batches do not postpone paint or geometry revision reads.
    with styles.batch_update():
        styles.opacity = 0.25
        assert node._subtree_style_revision != revision
        changed_revision = node._subtree_style_revision
        styles.color = "green"
        assert node._subtree_style_revision != changed_revision
        assert styles.color == Color.parse("green")
