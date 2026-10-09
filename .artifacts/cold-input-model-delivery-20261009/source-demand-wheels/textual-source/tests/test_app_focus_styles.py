"""Window focus invalidates declared dependencies, not every transcript row."""

from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.color import Color
from textual.containers import Container
from textual.widgets import Static


class FocusItem(Static):
    COMPONENT_CLASSES = {"focus-item--indicator"}


class FocusApp(App):
    CSS = """
    #affected { color: red; }
    App:blur #affected { color: blue; }
    FocusItem > .focus-item--indicator { color: red; }
    App:blur FocusItem > .focus-item--indicator { color: blue; }
    """

    def compose(self) -> ComposeResult:
        with Container(id="affected"):
            yield Static("inherits", id="child")
        yield FocusItem("component", id="component")
        for index in range(100):
            yield Static(str(index), id=f"unaffected-{index}")


async def test_app_focus_updates_inheritance_and_components_without_unrelated_rows():
    app = FocusApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        affected = app.query_one("#affected")
        component = app.query_one(FocusItem)
        child = app.query_one("#child")
        for focused, color in ((False, "blue"), (True, "red"), (False, "blue")):
            with patch.object(app.stylesheet, "apply", wraps=app.stylesheet.apply) as apply:
                app.app_focus = focused
                await pilot.pause()
                touched = {call.args[0] for call in apply.call_args_list}
                assert affected in touched and child not in touched and component in touched
                assert not any(node.id and node.id.startswith("unaffected-") for node in touched)
            assert affected.styles.color == Color.parse(color)
            assert component.get_component_styles("focus-item--indicator").color == Color.parse(color)
            before = child.rich_style
            # An unconditional native restyle must produce the same inherited
            # presentation as the dependency-filtered update.
            app.stylesheet.update(app.screen)
            assert child.rich_style == before


async def test_app_focus_cache_tracks_class_selected_app_rules():
    app = FocusApp()
    app.stylesheet.add_source(".scope:blur #child { background: green; }", read_from=("focus-test", ""))
    async with app.run_test() as pilot:
        app.add_class("scope")
        await pilot.pause()
        child = app.query_one("#child")
        original = child.styles.background
        app.app_focus = False
        await pilot.pause()
        assert child.styles.background == Color.parse("green")
        app.app_focus = True
        await pilot.pause()
        assert child.styles.background == original
