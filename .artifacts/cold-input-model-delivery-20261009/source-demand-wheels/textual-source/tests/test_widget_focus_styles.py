"""Focus changes preserve CSS while avoiding unrelated transcript restyles."""

from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.color import Color
from textual.containers import Container, VerticalScroll
from textual.widgets import Input, Static


class FocusContainer(Container, can_focus=True):
    pass


class FocusComponent(Static):
    COMPONENT_CLASSES = {"focus-component--indicator"}


class WidgetFocusApp(App):
    CSS = """
    #owner { height: 10; }
    #affected { color: red; height: 1; }
    #owner:blur #affected { color: blue; }
    FocusComponent > .focus-component--indicator { color: red; }
    #owner:blur FocusComponent > .focus-component--indicator { color: blue; }
    #outer { border: solid red; }
    #outer:focus-within { border: solid green; }
    """

    def compose(self) -> ComposeResult:
        with Container(id="outer"):
            with FocusContainer(id="owner"):
                with Container(id="affected"):
                    yield Static("inherited", id="inherited")
                yield FocusComponent("component")
                for index in range(50):
                    yield Static(str(index), classes="unaffected")
        yield Input(id="input")


async def test_widget_focus_targets_inheritance_components_and_ancestor_focus_within():
    app = WidgetFocusApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        owner = app.query_one("#owner")
        child = app.query_one("#inherited")
        affected = app.query_one("#affected")
        component = app.query_one(FocusComponent)
        for target, color, border in (
            (app.query_one(Input), "blue", "red"),
            (owner, "red", "green"),
            (None, "blue", "red"),
            (owner, "red", "green"),
        ):
            app.screen.set_focus(target, scroll_visible=False)
            await pilot.pause()
            assert affected.styles.color == Color.parse(color)
            assert component.get_component_styles("focus-component--indicator").color == Color.parse(color)
            assert app.query_one("#outer").styles.border_top[1] == Color.parse(border)
            before = child.rich_style
            app.stylesheet.update(owner)
            assert child.rich_style == before

        # Isolate the has_focus watcher from the independent ancestor
        # focus-within restyle performed by Screen.set_focus.
        with patch.object(app.stylesheet, "apply", wraps=app.stylesheet.apply) as apply:
            owner.has_focus = False
            touched = {call.args[0] for call in apply.call_args_list}
            assert affected in touched and child not in touched and component in touched
            assert not any(node.has_class("unaffected") for node in touched)


async def test_unstyled_focus_does_not_reapply_descendant_css_and_reload_is_observed():
    class TranscriptApp(App):
        def compose(self) -> ComposeResult:
            with FocusContainer(id="transcript"):
                for index in range(100):
                    yield Static(str(index), classes="row")

    app = TranscriptApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        transcript = app.query_one(FocusContainer)
        with patch.object(app.stylesheet, "apply", wraps=app.stylesheet.apply) as apply:
            transcript.has_focus = not transcript.has_focus
            assert not apply.called

        app.stylesheet.add_source(
            "#transcript:focus .row { color: red; } #transcript:blur .row { color: blue; }",
            read_from=("focus-reload-test", ""),
        )
        for focused, color in ((True, "red"), (False, "blue"), (True, "red")):
            transcript.has_focus = focused
            assert app.query_one(".row").styles.color == Color.parse(color)


async def test_focus_updates_virtual_scrollbar_styles():
    class ScrollApp(App):
        CSS = """
        VerticalScroll { height: 5; }
        Static { height: 1; }
        VerticalScroll:focus ScrollBar { color: red; }
        VerticalScroll:blur ScrollBar { color: blue; }
        """

        def compose(self) -> ComposeResult:
            with VerticalScroll():
                for index in range(20):
                    yield Static(str(index))

    app = ScrollApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        scroller = app.query_one(VerticalScroll)
        assert scroller.show_vertical_scrollbar
        for focused, color in ((False, "blue"), (True, "red"), (False, "blue")):
            scroller.has_focus = focused
            assert scroller.vertical_scrollbar.styles.color == Color.parse(color)
