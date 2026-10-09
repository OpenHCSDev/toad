from unittest.mock import patch

from textual.app import App
from textual.color import Color
from textual.containers import VerticalGroup
from textual.css.styles import Styles
from textual.widgets import Button, Label


async def test_focus_updates_targets_and_inherited_paint_without_restying_unrelated_rules():
    class FocusApp(App):
        AUTO_FOCUS = "#outside"
        CSS = """
        #host { color: blue; height: auto; }
        #host:focus-within { color: red; }
        #host:focus-within #target { text-style: bold; }
        """

        def compose(self):
            with VerticalGroup(id="host"):
                yield Button("inside", id="inside")
                yield Label("inherited", id="inherited")
                yield Label("target", id="target")
            yield Button("outside", id="outside")

    app = FocusApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        inherited = app.query_one("#inherited")
        target = app.query_one("#target")
        before = inherited.visual_style
        with patch.object(app.stylesheet, "apply", wraps=app.stylesheet.apply) as restyled:
            app.query_one("#inside").focus()
            await pilot.pause()
            assert inherited.visual_style.foreground != before.foreground
            assert target.visual_style.bold
            app.query_one("#outside").focus()
            await pilot.pause()
            assert inherited.visual_style.foreground == before.foreground
            assert not target.visual_style.bold
            assert all(call.args[0] is not inherited for call in restyled.call_args_list)


async def test_descendant_only_focus_within_rule_has_no_dependency_on_ancestor_rule_flags():
    class FocusApp(App):
        AUTO_FOCUS = "#outside"
        CSS = "#host:focus-within #target { color: red; } #target { color: blue; }"

        def compose(self):
            with VerticalGroup(id="host"):
                yield Button("inside", id="inside")
                yield Label("target", id="target")
            yield Button("outside", id="outside")

    app = FocusApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        target = app.query_one("#target")
        assert target.styles.color.css == "rgb(0,0,255)"
        app.query_one("#inside").focus()
        await pilot.pause()
        assert target.styles.color.css == "rgb(255,0,0)"
        app.query_one("#outside").focus()
        await pilot.pause()
        assert target.styles.color.css == "rgb(0,0,255)"


async def test_nested_focus_scopes_share_traversal_without_expanding_inner_targets():
    class FocusApp(App):
        CSS = """
        #outer:focus-within #outer-target { color: red; }
        #inner:focus-within .inner-target { color: green; }
        """

        def compose(self):
            with VerticalGroup(id="outer"):
                yield Label("outer", id="outer-target")
                yield Label("outside inner", id="outside-inner", classes="inner-target")
                with VerticalGroup(id="inner"):
                    yield Button("inside", id="inside")
                    yield Label("inner", id="inner-target", classes="inner-target")

    app = FocusApp()
    async with app.run_test() as pilot:
        app.query_one("#inside").focus()
        await pilot.pause()
        outer_target = app.query_one("#outer-target")
        inner_target = app.query_one("#inner-target")
        outside_inner = app.query_one("#outside-inner")
        with patch.object(app.stylesheet, "apply", wraps=app.stylesheet.apply) as restyled:
            app.stylesheet.update_focus_within(
                (app.query_one("#outer"), app.query_one("#inner"))
            )
        touched = [call.args[0] for call in restyled.call_args_list]
        assert touched.count(outer_target) == touched.count(inner_target) == 1
        assert outside_inner not in touched
        assert outer_target.styles.color == Color.parse("red")
        assert inner_target.styles.color == Color.parse("green")


async def test_focus_dependency_supply_follows_read_and_reparse(tmp_path):
    class Badge(Label):
        COMPONENT_CLASSES = {"badge--label"}

    class FocusApp(App):
        AUTO_FOCUS = "#outside"
        CSS = """
        .detail, .badge--label { color: blue; }
        """

        def compose(self):
            with VerticalGroup(id="host"):
                yield Button("inside", id="inside")
                yield Badge("target", classes="detail")
            yield Button("outside", id="outside")

    app = FocusApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        badge = app.query_one(Badge)
        # Acquire the original index before a new source is read. Both an
        # immediate descendant and a virtual component must gain its dependency.
        previous_index = app.stylesheet.rules_map
        path = tmp_path / "focus.tcss"
        path.write_text("""
        #host:focus-within > .detail { color: red; }
        #host:focus-within .badge--label { color: red; }
        """)
        app.stylesheet.read(path)
        app.query_one("#inside").focus()
        await pilot.pause()
        assert app.stylesheet.rules_map is not previous_index
        assert badge.styles.color == Color.parse("red")
        assert badge.get_component_styles("badge--label").color == Color.parse("red")

        path.write_text("""
        #host:focus-within > .detail { color: green; }
        #host:focus-within .badge--label { color: green; }
        """)
        app.stylesheet.read(path)
        app.stylesheet.reparse()
        app.query_one("#outside").focus()
        await pilot.pause()
        assert badge.styles.color == Color.parse("blue")
        assert badge.get_component_styles("badge--label").color == Color.parse("blue")
        app.query_one("#inside").focus()
        await pilot.pause()
        assert badge.styles.color == Color.parse("green")
        assert badge.get_component_styles("badge--label").color == Color.parse("green")


async def test_instant_style_changes_do_not_materialize_animation_rule_graphs():
    app = App()
    async with app.run_test() as pilot:
        label = Label("model")
        await app.mount(label)
        await pilot.pause()
        with patch.object(Styles, "get_render_rules", side_effect=AssertionError("Unrequested animation state")):
            app.stylesheet.replace_rules(label, {"color": Color.parse("red")}, animate=True)
            assert label.styles.color == Color.parse("red")
