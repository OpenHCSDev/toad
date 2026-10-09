"""Native source invalidation through real mounted line surfaces and chrome."""
from textual.app import App
from textual.containers import Container
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.scrollbar import ScrollBarRender
from textual.widgets import Log, RichLog, TextArea


async def test_native_line_measurements_survive_paint_and_retire_on_extent():
    lines = Log()
    editor = TextArea("saved\n" * 30)
    group = Container(lines, editor)

    class LinesApp(App):
        CSS = "Container { height: 12; } Log, TextArea { width: 30; height: 5; }"

        def compose(self):
            yield group

    async with LinesApp().run_test(size=(60, 18)) as pilot:
        lines.write_line("original retained row " * 10)
        await pilot.pause()
        chrome = tuple(child for widget in (lines, editor)
                       for child in widget._get_virtual_dom())
        assert chrome
        originals = {widget: widget._layout_updates for widget in (lines, editor, *chrome)}
        before = (lines.virtual_size, editor.virtual_size)
        group.styles.scrollbar_color = "red"
        assert {widget: widget._layout_updates for widget in originals} == originals
        await pilot.pause()
        assert (lines.virtual_size, editor.virtual_size) == before
        # Both original measurement methods follow the actual extent source.
        lines.virtual_size = Size(before[0].width + 2, before[0].height + 3)
        assert lines._layout_updates > originals[lines]
        assert lines.get_content_width(Size(10, 10), Size(60, 18)) == lines.virtual_size.width
        assert lines.get_content_height(Size(10, 10), Size(60, 18), 10) == lines.virtual_size.height
        # A live replacement renderer restores the conservative child contract.
        class CustomBar(ScrollBarRender):
            pass
        bar = editor.vertical_scrollbar
        bar.renderer = CustomBar
        before = editor._layout_updates, bar._layout_updates
        group.styles.scrollbar_color = "blue"
        assert editor._layout_updates > before[0] and bar._layout_updates > before[1]


async def test_custom_extent_and_method_supply_stays_conservative():
    class Computed(ScrollView):
        def compute_virtual_size(self):
            return Size(30, 30)

    class Replaced(ScrollView):
        @property
        def virtual_size(self):
            return Size(30, 30)

    class CustomHeight(ScrollView):
        def get_content_height(self, container, viewport, width):
            return 3

    for widget in (Computed(), Replaced(), CustomHeight(), RichLog()):
        assert (widget._content_height_dependency.styles_sensitive(widget)
                or widget._content_width_dependency.styles_sensitive(widget))
        before = widget._layout_updates
        widget.styles.scrollbar_color = "red"
        assert widget._layout_updates > before


def test_scrollbar_custom_declarations_and_live_method_replacement():
    from textual.scrollbar import ScrollBar, ScrollBarCorner

    class CustomBar(ScrollBar):
        pass

    class CustomCorner(ScrollBarCorner):
        pass

    assert CustomBar()._render_styles_sensitive()
    assert CustomCorner()._render_styles_sensitive()
    bar = ScrollBar()
    assert not bar._render_styles_sensitive()
    bar.render = lambda: "custom source"
    assert bar._render_styles_sensitive()
    corner = ScrollBarCorner()
    assert not corner._render_styles_sensitive()
    corner.render = lambda: "custom source"
    assert corner._render_styles_sensitive()
