from weakref import ref
from unittest.mock import patch

from rich.style import Style

from textual.color import Color
from textual.css.styles import Styles
from textual.dom import DOMNode
from textual.widget import Widget


def native_paint(node):
    background = Color(0, 0, 0, 0)
    foreground = Color(255, 255, 255, 0)
    opacity = 1.0
    style = Style()
    base_background = layered_background = Color(0, 0, 0, 0)
    for ancestor in reversed(node.ancestors_with_self):
        rules = ancestor.styles
        opacity *= rules.opacity
        text_background = background
        if rules.has_rule("background"):
            text_background = background + rules.background.tint(rules.background_tint)
            background += rules.background.tint(rules.background_tint).multiply_alpha(opacity)
        if rules.has_rule("color"):
            foreground = rules.color
        style += rules.text_style
        if rules.has_rule("auto_color") and rules.auto_color:
            foreground = text_background.get_contrast_text(foreground.a)
        base_background = layered_background
        layered_background += rules.background.tint(rules.background_tint).multiply_alpha(opacity)
    rich = style + Style.from_color(
        (background + foreground).rich_color if background.a or foreground.a else None,
        background.rich_color if background.a else None,
    )
    return background, foreground, style, opacity, (base_background, layered_background), rich


def test_inherited_paint_matches_native_math_across_mutations_and_moves():
    root, parent, leaf, alternative = Widget(), Widget(), Widget(), Widget()
    parent._parent = root
    leaf._parent = parent
    root.styles.background = "red 50%"
    root.styles.color = "white 40%"
    parent.styles.background = "blue 20%"
    parent.styles.background_tint = "green 10%"
    leaf.styles.text_style = "bold italic"
    for opacity in (1.0, .5, 0.0, .9):
        root.styles.opacity = opacity
        for auto in (False, True):
            parent.styles.auto_color = auto
            expected = native_paint(leaf)
            assert leaf.rich_style == expected[5]
            assert leaf.background_colors == expected[4]
            assert leaf.text_style == expected[2]
            assert leaf.opacity == expected[3]
            assert leaf.visual_style.background == expected[0]
            assert leaf.visual_style.foreground == expected[1]
    parent._parent = alternative
    assert leaf.rich_style == native_paint(leaf)[5]
    assert leaf.background_colors == native_paint(leaf)[4]


def test_paint_projection_does_not_own_ancestor_widgets():
    root, child = DOMNode(), DOMNode()
    child._parent = root
    child.rich_style
    owner = ref(root)
    del root
    assert owner() is None
    assert child.rich_style == native_paint(child)[5]


def test_unchanged_paint_does_not_rewalk_ancestors_and_raw_rules_invalidate():
    root, parent, leaf = Widget(), Widget(), Widget()
    parent._parent = root
    leaf._parent = parent
    leaf.rich_style
    with patch.object(parent, "_resolved_paint_state", wraps=parent._resolved_paint_state) as resolve:
        for _ in range(20):
            leaf.rich_style
            leaf.visual_style
            leaf.opacity
            leaf.background_colors
        resolve.assert_not_called()

    for mutate in (
        lambda: root.styles.set_rule("background", Color(255, 0, 0)),
        lambda: root.styles.merge_rules({"color": Color(0, 255, 0)}),
        lambda: root.styles.base.merge(Styles(_rules={"opacity": .5})),
        lambda: root.styles.clear_rule("background"),
        lambda: root.styles.inline.reset(),
        lambda: root.styles.base.reset(),
    ):
        mutate()
        assert leaf.rich_style == native_paint(leaf)[5]
        assert leaf.background_colors == native_paint(leaf)[4]
        assert leaf.opacity == native_paint(leaf)[3]


def test_custom_ancestry_does_not_use_native_mutation_epoch():
    first, second = Widget(), Widget()
    first.styles.background = "red"
    second.styles.background = "blue"

    class Custom(Widget):
        ancestor = first

        @property
        def ancestors_with_self(self):
            return [self, self.ancestor]

    custom, child = Custom(), Widget()
    child._parent = custom
    before = child.rich_style
    custom.ancestor = second
    assert custom.rich_style == native_paint(custom)[5]
    assert child.rich_style != before


def test_style_views_and_unchanged_rules_preserve_paint_until_original_mutation():
    root, leaf = Widget(), Widget()
    leaf._parent = root
    root.styles.color = "red"
    before = leaf.rich_style
    paint_epoch = leaf._paint_epoch
    rules_key = root.styles._cache_key

    # Parsing and serializing declarations do not modify a widget. Merging
    # equal rules and resetting an empty inline source also leave it unchanged.
    detached = Styles.parse("color: blue;", read_from=("test", ""))
    detached.merge_rules({"opacity": .5})
    detached.reset()
    root.styles.css
    root.styles.merge_rules(root.styles.inline.get_rules())
    root.styles.base.merge(root.styles.base)
    root.styles.base.reset()
    assert root.styles._cache_key == rules_key
    assert leaf.rich_style == before
    assert leaf._paint_epoch == paint_epoch

    # Genuine bulk writes and removals are visible immediately, including
    # reads inside the existing synchronous refresh batch.
    with root.styles.batch_update():
        root.styles.merge_rules({"color": Color.parse("blue")})
        assert leaf.rich_style.color == Color.parse("blue").rich_color
        root.styles.reset()
        assert leaf.rich_style == native_paint(leaf)[5]
        assert leaf.rich_style != before

    # A stored initial declaration and a missing rule are different sources.
    initial = Styles()
    initial.merge_rules({"color": None})
    assert initial.has_rule("color")
    initial.reset()
    assert not initial.has_rule("color")


def test_layout_dependency_changes_preserve_retained_paint_values():
    root, parent, leaf = Widget(), Widget(), Widget()
    parent._parent = root
    leaf._parent = parent
    root.styles.color = "red"
    original = leaf._resolved_paint_state()
    visual = leaf.visual_style

    # A tab's visibility changes dependency epochs without changing pixels.
    for visible in (False, True):
        parent.display = visible
        current = leaf._resolved_paint_state()
        assert current is not original
        assert current != original
        assert original.same_paint(current)
        assert leaf.visual_style is visual

    # Real inherited paint changes remain invalidating, including opacity.
    parent.styles.opacity = .5
    assert not original.same_paint(leaf._resolved_paint_state())
    parent.styles.opacity = 1
    parent.styles.color = "blue"
    assert not original.same_paint(leaf._resolved_paint_state())
    assert leaf.visual_style is not visual


def test_custom_lazy_ancestry_retains_original_uncacheable_paint_contract():
    first, second = Widget(), Widget()
    first.styles.background = "red"
    second.styles.background = "blue"

    class CustomWalk(Widget):
        ancestor = first

        def walk_ancestors(self, *, with_self=False):
            if with_self:
                yield self
            yield self.ancestor

    custom, child = CustomWalk(), Widget()
    child._attach(custom)
    before = child.rich_style
    custom.ancestor = second
    assert custom.rich_style == native_paint(custom)[5]
    assert child.rich_style != before
