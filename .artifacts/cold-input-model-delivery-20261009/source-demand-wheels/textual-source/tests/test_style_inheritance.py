from textual.app import App, ComposeResult
from textual.widgets import Button, Static


def test_visual_style_preserves_declared_flags():
    from rich.style import Style as RichStyle
    from textual.style import Style

    original = RichStyle(reverse=True, underline2=True, blink=True, overline=True)
    converted = Style.from_rich_style(original)
    assert converted.rich_style == original
    assert converted.without_color.rich_style == original
    assert converted.rich_style_with_offset(2, 3).overline is True
    assert (converted + Style(overline=False, reverse=False)).rich_style.overline is False
    assert (converted + Style(overline=False, reverse=False)).rich_style.reverse is False
    assert Style(overline=True) != Style()
    assert not Style(overline=True)._is_null
    assert Style(overline=True).style_definition == "overline"


async def test_component_and_widget_render_keep_declared_text_flags():
    from textual.widgets import OptionList

    class StyleApp(App):
        CSS = """
        OptionList > .option-list--option-highlighted {
            text-style: reverse blink overline;
        }
        Static { text-style: reverse blink overline; }
        """

        def compose(self):
            yield OptionList("selected")
            yield Static("sidebar", id="row")

    async with StyleApp().run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        options = pilot.app.query_one(OptionList)
        row = pilot.app.query_one("#row", Static)
        component = options.get_visual_style("option-list--option-highlighted")
        for style in (component.rich_style, row.visual_style.rich_style):
            assert style.reverse and style.blink and style.overline
        for widget, word in ((options, "selected"), (row, "sidebar")):
            segments = [segment for strip in widget.render_lines(widget.region.reset_offset)
                        for segment in strip if word in segment.text]
            assert segments
            assert all(segment.style.reverse and segment.style.blink
                       and segment.style.overline for segment in segments)


async def test_text_style_inheritance():
    """Check that changes to text style are inherited in children."""

    class FocusableThing(Static, can_focus=True):
        DEFAULT_CSS = """
        FocusableThing {
            text-style: bold;
        }

        FocusableThing:focus {
            text-style: bold reverse;
        }
        """

        def compose(self) -> ComposeResult:
            yield Static("test", id="child-of-focusable-thing")

    class InheritanceApp(App):
        def compose(self) -> ComposeResult:
            yield Button("button1", id="initial-focus")
            yield FocusableThing()
            yield Button("button2")

    app = InheritanceApp()
    async with app.run_test() as pilot:
        # Headless startup does not promise application-focus admission.
        # Establish the starting widget before testing the Tab transition.
        initial_focus = app.query_one("#initial-focus", Button)
        initial_focus.focus()
        await pilot.pause()
        assert app.focused is initial_focus
        child = app.query_one("#child-of-focusable-thing")
        assert child.rich_style.bold
        assert not child.rich_style.reverse
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is app.query_one(FocusableThing)
        assert child.rich_style.bold
        assert child.rich_style.reverse
