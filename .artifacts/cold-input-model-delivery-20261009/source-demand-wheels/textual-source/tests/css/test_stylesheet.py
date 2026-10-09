from contextlib import nullcontext as does_not_raise
from unittest.mock import patch
import gc
import weakref

import pytest

from textual.app import App, ComposeResult
from textual.color import Color
from textual.containers import Container
from textual.css.model import RuleSet
from textual.css.stylesheet import CssSource, Stylesheet, StylesheetParseError
from textual.css.tokenizer import TokenError
from textual.css.transition import Transition
from textual.dom import DOMNode
from textual.geometry import Spacing
from textual.widget import Widget
from textual.widgets import Static


async def test_inline_style_uses_own_stylesheet_variables():
    class DifferentVariablesApp(App):
        def get_css_variables(self):
            return {**super().get_css_variables(), "document-color": "red"}

    stylesheet = Stylesheet(variables={"document-color": "blue"})
    async with DifferentVariablesApp().run_test():
        assert stylesheet.parse_style("$document-color").foreground == Color.parse(
            "blue"
        )
        stylesheet.set_variables({"document-color": "green"})
        assert stylesheet.parse_style("$document-color").foreground == Color.parse(
            "green"
        )


def test_target_rule_publication_acquires_only_declared_css_path():
    class PathReads(DOMNode):
        path_reads = 0

        @property
        def css_path_nodes(self):
            self.path_reads += 1
            return super().css_path_nodes

    parent = DOMNode(classes="outer")
    node = PathReads(classes="leaf")
    node._attach(parent)
    stylesheet = Stylesheet()
    stylesheet.add_source(".leaf { color: red; }")
    stylesheet.apply(node)
    assert node.styles.color == Color.parse("red")
    assert node.path_reads == 0

    # Reparse a real child declaration: full ancestry and specificity must
    # become authoritative again, not the previous target-only key.
    stylesheet.add_source(".outer > .leaf { color: blue; }")
    stylesheet.apply(node)
    assert node.styles.color == Color.parse("blue")
    assert node.path_reads == 1


async def test_equal_current_rules_retarget_a_pending_transition():
    app = App()
    async with app.run_test() as pilot:
        widget = Static("transition target")
        await app.mount(widget)
        await pilot.pause()
        rules = {**widget.styles.base.get_rules(), "opacity": 1.0,
                 "transitions": {"opacity": Transition(1, "linear", 60)}}
        Stylesheet.replace_rules(widget, rules)
        Stylesheet.replace_rules(widget, {**rules, "opacity": .5}, animate=True)
        assert app.animator.is_being_animated(widget.styles.base, "opacity")
        assert widget.styles.base.opacity == 1.0
        with patch.object(app.animator, "animate", wraps=app.animator.animate) as animate:
            Stylesheet.replace_rules(widget, rules, animate=True)
            animate.assert_called_once()
            assert animate.call_args.args == (widget.styles.base, "opacity", 1.0)


@pytest.mark.parametrize("from_css", [False, True])
async def test_related_inherited_rules_invalidate_descendants_once(from_css):
    app = App()
    async with app.run_test() as pilot:
        child = Static("inherited styles")
        parent = Container(child)
        await app.mount(parent)
        await pilot.pause()
        child.rich_style  # Populate the inherited style cache before the edit.
        with patch.object(child, "notify_style_update", wraps=child.notify_style_update) as notify:
            if from_css:
                rules = {**parent.styles.base.get_rules(), "color": Color.parse("red"),
                         "background": Color.parse("blue"), "text_style": "bold"}
                Stylesheet.replace_rules(parent, rules)
            else:
                parent.set_styles(color="red", background="blue", text_style="bold")
            assert notify.call_count == 1
        await pilot.pause()
        assert child.rich_style.color == Color.parse("red").rich_color
        assert child.rich_style.bold
        assert parent.styles.background == Color.parse("blue")


async def test_style_batch_keeps_child_damage_separate_and_flushes_interrupted_edits():
    from textual.css.errors import StyleValueError

    app = App()
    async with app.run_test() as pilot:
        child = Static("cached child")
        parent = Container(child)
        await app.mount(parent)
        await pilot.pause()
        child.rich_style
        with patch.object(child, "refresh", wraps=child.refresh) as refresh:
            with parent.styles.batch_update():
                parent.styles.refresh(layout=True)
                with parent.styles.batch_update():
                    parent.styles.color = "green"
            refresh.assert_called_once_with(repaint=True)
            assert not child._layout_required
        assert child.rich_style.color == Color.parse("green").rich_color
        with pytest.raises(StyleValueError), parent.styles.batch_update():
            parent.styles.color = "red"
            parent.styles.text_style = "bold"
            parent.styles.align_horizontal = "invalid"
        assert child.rich_style.color == Color.parse("red").rich_color
        assert child.rich_style.bold
        # An interrupted edit must release the lifetime for later individual edits.
        with patch.object(child, "notify_style_update", wraps=child.notify_style_update) as notify:
            parent.styles.color = "blue"
            notify.assert_called_once()


def test_component_styles_own_node_without_a_collection_cycle():
    from textual.css.stylesheet import _ComponentStyles

    enabled = gc.isenabled()
    gc.disable()
    try:
        node = DOMNode(classes="detail")
        styles = _ComponentStyles(node)
        reference = weakref.ref(node)
        styles.color = "red"
        del node
        assert reference() is not None, "Live component styles lost their virtual node"
        assert styles.node is reference()
        assert styles.node.styles.color == Color.parse("red")
        del styles
        assert reference() is None, "Discarded component node requires cyclic GC"
    finally:
        if enabled:
            gc.enable()


def test_styles_do_not_keep_retired_node_alive():
    enabled = gc.isenabled()
    gc.disable()
    try:
        node = DOMNode()
        reference = weakref.ref(node)
        styles = node.styles.base
        styles.color = "blue"
        copied = styles.copy()
        assert copied.node is node and styles.node is node
        del node
        assert reference() is None, "Node/styles ownership still requires cyclic GC"
        assert styles.node is None and copied.node is None
        # Detached rules remain usable without an owner to notify.
        assert styles.color == Color.parse("blue")
        copied.color = "green"
        copied.refresh()
    finally:
        if enabled:
            gc.enable()


async def test_css_path_cache_reuses_equivalent_rows_without_crossing_hover():
    class RowsApp(App):
        CSS = """
        Container.row > Static.item { color: red; }
        Container.row:hover > Static.item { color: blue; }
        #one > Static.item { color: green; }
        """

        def compose(self) -> ComposeResult:
            with Container(classes="row", id="one"):
                yield Static("first", classes="item")
            with Container(classes="row", id="two"):
                yield Static("second", classes="item")

    app = RowsApp()
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        first = app.query_one("#one Static", Static)
        second = app.query_one("#two Static", Static)
        # The first result may be parent-id specific; distinct ids must not
        # share an ancestry cache key even when their classes look identical.
        cache = {}
        app.stylesheet._path_rules_cache.clear()
        with patch.object(RuleSet, "check", autospec=True, side_effect=RuleSet.check) as check:
            app.stylesheet.apply(first, cache=cache)
            called = check.call_count
            assert called
            app.stylesheet.apply(second, cache=cache)
            assert check.call_count > called
        assert first.styles.color == Color.parse("green")
        assert second.styles.color == Color.parse("red")

        await pilot.hover(app.query_one("#two", Container))
        await pilot.pause()
        app.query_one("#two", Container).mouse_hover = True
        with patch.object(RuleSet, "check", autospec=True, side_effect=RuleSet.check) as check:
            app.stylesheet.apply(second, cache=cache)
            assert check.call_count > 0, "Ancestor hover must invalidate the path key"
        assert second.styles.color == Color.parse("blue")
        assert first.styles.color == Color.parse("green")


async def test_css_path_cache_hits_across_equivalent_parent_instances():
    class RowsApp(App):
        CSS = "Container.row > Static.item { color: red; }"

        def compose(self) -> ComposeResult:
            for _ in range(2):
                with Container(classes="row"):
                    yield Static("member", classes="item")

    app = RowsApp()
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        first, second = tuple(app.query("Static.item"))
        assert first.parent is not second.parent
        cache = {}
        app.stylesheet._path_rules_cache.clear()
        with patch.object(RuleSet, "check", autospec=True, side_effect=RuleSet.check) as check:
            app.stylesheet.apply(first, cache=cache)
            called = check.call_count
            assert called
            app.stylesheet.apply(second, cache={})
            assert check.call_count == called, "Equivalent rows still rematched CSS rules"
        assert first.styles.color == second.styles.color == Color.parse("red")


async def test_component_style_reuses_unchanged_node_but_tracks_css_and_ancestry():
    class Badge(Static):
        COMPONENT_CLASSES = {"badge--label"}

    class BadgeApp(App):
        CSS = """
        Badge > .badge--label { color: red; }
        Badge.alert > .badge--label { color: blue; }
        """

        def compose(self) -> ComposeResult:
            yield Container(Badge("first"), id="unused-left")
            yield Container(id="unused-right")

    app = BadgeApp()
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        badge = app.query_one(Badge)
        stylesheet = app.stylesheet
        original = badge._component_styles["badge--label"]
        stylesheet.apply(badge)
        assert badge._component_styles["badge--label"] is original
        # Physical source custody may change an ID that no rule references.
        # This must not replace an unchanged component's native style owner.
        badge.reparent(app.query_one("#unused-right", Container))
        await pilot.pause()
        assert badge._component_styles["badge--label"] is original
        badge.reparent(app.query_one("#unused-left", Container))
        await pilot.pause()
        assert badge._component_styles["badge--label"] is original
        badge.add_class("alert")
        await pilot.pause()
        assert badge.get_component_styles("badge--label").color == Color.parse("blue")
        assert badge._component_styles["badge--label"] is original
        updated = badge._component_styles["badge--label"]
        stylesheet.add_source("Badge.alert > .badge--label { color: green; }",
                              read_from=("badge-test", "override"))
        stylesheet.parse()
        stylesheet.apply(badge)
        assert badge.get_component_styles("badge--label").color == Color.parse("green")
        assert badge._component_styles["badge--label"] is updated
        stylesheet.add_source("#unused-right Badge.alert > .badge--label { color: yellow; }",
                              read_from=("badge-test", "ancestor"))
        stylesheet.parse()
        badge.reparent(app.query_one("#unused-right", Container))
        await pilot.pause()
        assert badge.get_component_styles("badge--label").color == Color.parse("yellow")
        badge.reparent(app.query_one("#unused-left", Container))
        await pilot.pause()
        assert badge.get_component_styles("badge--label").color == Color.parse("green")


async def test_component_style_keeps_focus_within_on_uncached_path():
    from textual.css.styles import Styles
    from textual.message_pump import MessagePump

    class Badge(Static):
        COMPONENT_CLASSES = {"badge--label"}

    class BadgeApp(App):
        CSS = "Badge:focus-within > .badge--label { color: blue; }"

        def compose(self) -> ComposeResult:
            yield Badge("first")

    app = BadgeApp()
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        badge = app.query_one(Badge)
        previous = badge._component_styles["badge--label"]
        previous_node = previous.node
        epochs = Styles._revision, MessagePump._tree_revision
        app.stylesheet.apply(badge)
        assert badge._component_styles["badge--label"] is previous
        assert previous.node is previous_node
        assert (Styles._revision, MessagePump._tree_revision) == epochs
        assert badge._component_css_signature is None


def _make_user_stylesheet(css: str) -> Stylesheet:
    stylesheet = Stylesheet()
    stylesheet.source["test.tcss"] = CssSource(css, is_defaults=False)
    stylesheet.parse()
    return stylesheet


def test_stylesheet_apply_highest_specificity_wins():
    """#ids have higher specificity than .classes"""
    css = "#id {color: red;} .class {color: blue;}"
    stylesheet = _make_user_stylesheet(css)
    node = DOMNode(classes="class", id="id")
    stylesheet.apply(node)

    assert node.styles.color == Color(255, 0, 0)


def test_stylesheet_apply_doesnt_override_defaults():
    css = "#id {color: red;}"
    stylesheet = _make_user_stylesheet(css)
    node = DOMNode(id="id")
    stylesheet.apply(node)

    assert node.styles.margin == Spacing.all(0)
    assert node.styles.box_sizing == "border-box"


def test_stylesheet_apply_highest_specificity_wins_multiple_classes():
    """When we use two selectors containing only classes, then the selector
    `.b.c` has greater specificity than the selector `.a`"""
    css = ".b.c {background: blue;} .a {background: red; color: lime;}"
    stylesheet = _make_user_stylesheet(css)
    node = DOMNode(classes="a b c")
    stylesheet.apply(node)

    assert node.styles.background == Color(0, 0, 255)
    assert node.styles.color == Color(0, 255, 0)


def test_stylesheet_many_classes_dont_overrule_id():
    """#id is further to the left in the specificity tuple than class, and
    a selector containing multiple classes cannot take priority over even a
    single class."""
    css = "#id {color: red;} .a.b.c.d {color: blue;}"
    stylesheet = _make_user_stylesheet(css)
    node = DOMNode(classes="a b c d", id="id")
    stylesheet.apply(node)

    assert node.styles.color == Color(255, 0, 0)


def test_stylesheet_last_rule_wins_when_same_rule_twice_in_one_ruleset():
    css = "#id {color: red; color: blue;}"
    stylesheet = _make_user_stylesheet(css)
    node = DOMNode(id="id")
    stylesheet.apply(node)

    assert node.styles.color == Color(0, 0, 255)


def test_stylesheet_rulesets_merged_for_duplicate_selectors():
    css = "#id {color: red; background: lime;} #id {color:blue;}"
    stylesheet = _make_user_stylesheet(css)
    node = DOMNode(id="id")
    stylesheet.apply(node)

    assert node.styles.color == Color(0, 0, 255)
    assert node.styles.background == Color(0, 255, 0)


def test_stylesheet_apply_takes_final_rule_in_specificity_clash():
    """.a and .b both contain background and have same specificity, so .b wins
    since it was declared last - the background should be blue."""
    css = ".a {background: red; color: lime;} .b {background: blue;}"
    stylesheet = _make_user_stylesheet(css)
    node = DOMNode(classes="a b", id="c")
    stylesheet.apply(node)

    assert node.styles.color == Color(0, 255, 0)  # color: lime
    assert node.styles.background == Color(0, 0, 255)  # background: blue


def test_stylesheet_apply_empty_rulesets():
    """Ensure that we don't crash when working with empty rulesets"""
    css = ".a {} .b {}"
    stylesheet = _make_user_stylesheet(css)
    node = DOMNode(classes="a b")
    stylesheet.apply(node)


def test_stylesheet_apply_user_css_over_widget_css():
    user_css = ".a {color: red; tint: yellow;}"

    class MyWidget(Widget):
        DEFAULT_CSS = ".a {color: blue !important; background: lime;}"

    node = MyWidget()
    node.add_class("a")

    stylesheet = _make_user_stylesheet(user_css)
    stylesheet.add_source(
        MyWidget.DEFAULT_CSS, "widget.py:MyWidget", is_default_css=True
    )
    stylesheet.apply(node)

    # The node is red because user CSS overrides Widget.DEFAULT_CSS
    assert node.styles.color == Color(255, 0, 0)
    # The background colour defined in the Widget still applies, since user CSS doesn't override it
    assert node.styles.background == Color(0, 255, 0)
    # As expected, the tint colour is yellow, since there's no competition between user or widget CSS
    assert node.styles.tint == Color(255, 255, 0)


@pytest.mark.parametrize(
    "css_value,expectation,expected_color",
    [
        # Valid values:
        ["transparent", does_not_raise(), Color(0, 0, 0, 0)],
        ["ansi_red", does_not_raise(), Color(128, 0, 0, ansi=1)],
        ["ansi_bright_magenta", does_not_raise(), Color(255, 0, 255, ansi=13)],
        ["red", does_not_raise(), Color(255, 0, 0)],
        ["lime", does_not_raise(), Color(0, 255, 0)],
        ["coral", does_not_raise(), Color(255, 127, 80)],
        ["aqua", does_not_raise(), Color(0, 255, 255)],
        ["deepskyblue", does_not_raise(), Color(0, 191, 255)],
        ["rebeccapurple", does_not_raise(), Color(102, 51, 153)],
        ["#ffcc00", does_not_raise(), Color(255, 204, 0)],
        ["#ffcc0033", does_not_raise(), Color(255, 204, 0, 0.2)],
        ["rgb(200,90,30)", does_not_raise(), Color(200, 90, 30)],
        ["rgba(200,90,30,0.3)", does_not_raise(), Color(200, 90, 30, 0.3)],
        # Some invalid ones:
        ["coffee", pytest.raises(StylesheetParseError), None],  # invalid color name
        ["ansi_dark_cyan", pytest.raises(StylesheetParseError), None],
        ["red 4", pytest.raises(StylesheetParseError), None],  # space in it
        ["1", pytest.raises(StylesheetParseError), None],  # invalid value
        ["()", pytest.raises(TokenError), None],  # invalid tokens
    ],
)
def test_color_property_parsing(css_value, expectation, expected_color):
    stylesheet = Stylesheet()
    css = """
    * {
      background: ${COLOR};
    }
    """.replace(
        "${COLOR}", css_value
    )

    with expectation:
        stylesheet.add_source(css)
        stylesheet.parse()

    if expected_color:
        css_rule = stylesheet.rules[0]
        assert css_rule.styles.background == expected_color


@pytest.mark.parametrize(
    "css_property_name,expected_property_name_suggestion",
    [
        ["backgroundu", "background"],
        ["bckgroundu", "background"],
        ["ofset-x", "offset-x"],
        ["ofst_y", "offset-y"],
        ["colr", "color"],
        ["colour", "color"],
        ["wdth", "width"],
        ["wth", "width"],
        ["wh", None],
        ["xkcd", None],
    ],
)
def test_did_you_mean_for_css_property_names(
    css_property_name: str, expected_property_name_suggestion
):
    stylesheet = Stylesheet()
    css = """
    * {
      border: blue;
      ${PROPERTY}: red;
    }
    """.replace(
        "${PROPERTY}", css_property_name
    )

    stylesheet.add_source(css)
    with pytest.raises(StylesheetParseError) as err:
        stylesheet.parse()

    _, help_text = err.value.errors.rules[0].errors[0]  # type: Any, HelpText
    displayed_css_property_name = css_property_name.replace("_", "-")
    expected_summary = f"Invalid CSS property {displayed_css_property_name!r}"
    if expected_property_name_suggestion:
        expected_summary += f". Did you mean '{expected_property_name_suggestion}'?"
    assert help_text.summary == expected_summary


@pytest.mark.parametrize(
    "css_property_name,expected_property_name_suggestion",
    [
        ["backgroundu", "background"],
        ["bckgroundu", "background"],
        ["ofset-x", "offset-x"],
        ["ofst_y", "offset-y"],
        ["colr", "color"],
        ["colour", "color"],
        ["wdth", "width"],
        ["wth", "width"],
        ["wh", None],
        ["xkcd", None],
    ],
)
def test_did_you_mean_for_property_names_in_nested_css(
    css_property_name: str, expected_property_name_suggestion: "str | None"
) -> None:
    """Test that we get nice errors with mistyped declaractions in nested CSS.

    When implementing pseudo-class support in nested TCSS
    (https://github.com/Textualize/textual/issues/4039), the first iterations didn't
    preserve this so we add these tests to make sure we don't take this feature away
    unintentionally.
    """
    stylesheet = Stylesheet()
    css = """
    Screen {
        * {
            border: blue;
            ${PROPERTY}: red;
        }
    }
    """.replace(
        "${PROPERTY}", css_property_name
    )

    stylesheet.add_source(css)
    with pytest.raises(StylesheetParseError) as err:
        stylesheet.parse()

    _, help_text = err.value.errors.rules[1].errors[0]
    displayed_css_property_name = css_property_name.replace("_", "-")
    expected_summary = f"Invalid CSS property {displayed_css_property_name!r}"
    if expected_property_name_suggestion:
        expected_summary += f". Did you mean '{expected_property_name_suggestion}'?"
    assert help_text.summary == expected_summary


@pytest.mark.parametrize(
    "css_property_name,css_property_value,expected_color_suggestion",
    [
        ["color", "blu", "blue"],
        ["background", "chartruse", "chartreuse"],
        ["tint", "ansi_whi", "ansi_white"],
        ["scrollbar-color", "transprnt", "transparent"],
        ["color", "xkcd", None],
    ],
)
def test_did_you_mean_for_color_names(
    css_property_name: str, css_property_value: str, expected_color_suggestion
):
    stylesheet = Stylesheet()
    css = """
    * {
      border: blue;
      ${PROPERTY}: ${VALUE};
    }
    """.replace(
        "${PROPERTY}", css_property_name
    ).replace(
        "${VALUE}", css_property_value
    )

    stylesheet.add_source(css)
    with pytest.raises(StylesheetParseError) as err:
        stylesheet.parse()

    _, help_text = err.value.errors.rules[0].errors[0]  # type: Any, HelpText
    displayed_css_property_name = css_property_name.replace("_", "-")
    expected_error_summary = f"Invalid value ({css_property_value!r}) for the [i]{displayed_css_property_name}[/] property"

    if expected_color_suggestion is not None:
        expected_error_summary += f". Did you mean '{expected_color_suggestion}'?"

    assert help_text.summary == expected_error_summary
