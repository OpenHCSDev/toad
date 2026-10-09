import pytest

from textual.app import App
from textual.containers import Grid
from textual.widgets import Label


async def test_pointer_shape_preserves_native_measurement_and_unknown_renderers():
    """Cursor publication has no native size input; custom renderers retain it."""
    from textual.content import Content
    from textual.widgets import Static

    class PointerContent(Static):
        def render(self):
            return Content(self.styles.pointer)

    native, custom = Label("original row"), PointerContent()
    app = App()
    async with app.run_test(size=(40, 12)) as pilot:
        await app.mount(native, custom)
        await pilot.pause()
        await pilot.hover(native)
        before = native.region
        measurement, geometry = native._layout_updates, native._geometry_revision
        custom_measurement = custom._layout_updates
        native.styles.pointer = "text"
        assert app.screen._pointer_shape == "text"
        assert native._layout_updates == measurement
        assert native._geometry_revision == geometry
        custom.styles.pointer = "crosshair"
        assert custom._layout_updates > custom_measurement
        await pilot.pause()
        assert native.region == before
        assert app.screen.get_widget_at(before.x, before.y)[0] is native
        # Raw source writes and stylesheet replacement share the descriptor.
        native._inline_styles.set_rule("pointer", "pointer")
        native._css_styles.replace_rules(dict(native._css_styles.get_rules(), pointer="help"))
        assert native._layout_updates == measurement
        assert native._geometry_revision == geometry
        # Not every unscheduled enum is paint-only: wrapping remains a size input.
        native.styles.text_wrap = "nowrap"
        assert native._layout_updates > measurement


async def test_style_publication_preserves_source_and_content_lifetimes():
    """A frame request must not retire measurements twice or hide new content."""
    from textual.css.scalar import Scalar

    app = App()
    async with app.run_test(size=(40, 12)) as pilot:
        widget = Label("one")
        await app.mount(widget)
        await pilot.pause()
        updates = widget._layout_updates
        geometry = app.screen._geometry_revision
        widget._inline_styles.set_rule("width", Scalar.parse("12"))
        assert widget._layout_updates == updates + 1
        assert app.screen._geometry_revision > geometry
        assert not widget._layout_required
        widget._inline_styles.refresh(layout=True, repaint=False)
        assert widget._layout_updates == updates + 1
        await pilot.pause()
        assert widget.size.width == 12

        updates = widget._layout_updates
        geometry = app.screen._geometry_revision
        widget.update("one\ntwo\nthree")
        assert widget._layout_updates == updates + 1
        assert app.screen._geometry_revision > geometry
        await pilot.pause()
        assert widget.size.height == 3
        assert "three" in widget.render_line(2).text


async def test_app_style_publication_keeps_current_screen_layout():
    """App style damage must reach its current Screen without retiring it twice."""
    app = App()
    async with app.run_test(size=(40, 12)) as pilot:
        widget = Label("current screen")
        await app.mount(widget)
        await pilot.pause()
        updates = app.screen._layout_updates
        app.styles.padding = (1, 2)
        assert app.screen._layout_updates == updates + 1
        assert app.screen._layout_required
        await pilot.pause()
        assert not app.screen._layout_required
        assert widget in app.screen._compositor.visible_widgets


@pytest.mark.parametrize(
    "style, value",
    [
        ("grid_size_rows", 3),
        ("grid_size_columns", 3),
        ("grid_gutter_vertical", 4),
        ("grid_gutter_horizontal", 4),
        ("grid_rows", "1fr 3fr"),
        ("grid_columns", "1fr 3fr"),
    ],
)
async def test_programmatic_style_change_updates_children(style: str, value: object):
    """Regression test for #1607 https://github.com/Textualize/textual/issues/1607

    Some programmatic style changes to a widget were not updating the layout of the
    children widgets, which seemed to be happening when the style change did not affect
    the size of the widget but did affect the layout of the children.

    This test, in particular, checks the attributes that _should_ affect the size of the
    children widgets.
    """

    class MyApp(App[None]):
        CSS = """
        Grid { grid-size: 2 2; }
        Label { width: 100%; height: 100%; }
        """

        def compose(self):
            yield Grid(
                Label("one"),
                Label("two"),
                Label("three"),
                Label("four"),
            )

    app = MyApp()

    async with app.run_test() as pilot:
        sizes = [(lbl.size.width, lbl.size.height) for lbl in app.screen.query(Label)]

        setattr(app.query_one(Grid).styles, style, value)
        await pilot.pause()

        assert sizes != [
            (lbl.size.width, lbl.size.height) for lbl in app.screen.query(Label)
        ]


@pytest.mark.parametrize(
    "style, value",
    [
        ("align_horizontal", "right"),
        ("align_vertical", "bottom"),
        ("align", ("right", "bottom")),
    ],
)
async def test_programmatic_align_change_updates_children_position(
    style: str, value: str
):
    """Regression test for #1607 for the align(_xxx) styles.

    See https://github.com/Textualize/textual/issues/1607.
    """

    class MyApp(App[None]):
        CSS = "Grid { grid-size: 2 2; }"

        def compose(self):
            yield Grid(
                Label("one"),
                Label("two"),
                Label("three"),
                Label("four"),
            )

    app = MyApp()

    async with app.run_test() as pilot:
        offsets = [(lbl.region.x, lbl.region.y) for lbl in app.screen.query(Label)]

        setattr(app.query_one(Grid).styles, style, value)
        await pilot.pause()

        assert offsets != [
            (lbl.region.x, lbl.region.y) for lbl in app.screen.query(Label)
        ]


async def test_keyword_cohort_publishes_once_and_keeps_normalized_source():
    from textual.css.errors import StyleValueError

    app = App()
    async with app.run_test(size=(40, 12)) as pilot:
        widget = Label("cohort content")
        await app.mount(widget)
        await pilot.pause()
        updates = widget._inline_styles._updates
        widget.set_styles(width=12, min_width=12, max_width=12,
                          dock="left", position="relative", overlay="none", offset=(2, 1))
        assert widget._inline_styles._updates == updates + 1
        await pilot.pause()
        assert widget.size.width == 12
        assert widget.region.offset == (2, 1)
        assert widget.styles.width.value == 12
        normalized = widget._inline_styles.get_rules()
        widget.set_styles(width="12", min_width=12, max_width="12", offset=("2", "1"))
        assert widget._inline_styles._updates == updates + 1
        assert widget._inline_styles.get_rules() == normalized
        with pytest.raises(StyleValueError):
            widget.set_styles(width=20, color="red", align_horizontal="invalid")
        assert widget._inline_styles.get_rules() == normalized
        assert widget._inline_styles._updates == updates + 1
        widget.set_styles(offset=None, min_width=None, max_width=None, width=8)
        assert widget._inline_styles._updates == updates + 2
        assert not widget._inline_styles.has_rule("offset")
        await pilot.pause()
        assert widget.size.width == 8
        assert widget.region.offset == (0, 0)
        widget.set_styles(display="none")
        await pilot.pause()
        assert widget not in app.screen._compositor.visible_widgets
        widget.set_styles(display="block")
        await pilot.pause()
        assert widget in app.screen._compositor.visible_widgets


async def test_offset_only_cohort_moves_native_scene_without_repainting_content():
    app = App()
    async with app.run_test(size=(40, 12)) as pilot:
        widget = Label("retained row")
        widget.set_styles(width=12, height=1)
        await app.mount(widget)
        await pilot.pause()
        row = widget.render_line(0)
        cache = widget._render_cache
        before = widget.region
        widget.set_styles(offset=(3, 2))
        assert not widget._repaint_required
        assert widget._render_cache is cache
        await pilot.pause()
        assert widget.region == before.translate((3, 2))
        assert widget.render_line(0) is row
        assert widget._render_cache is cache
        compositor = app.screen._compositor
        assert compositor.get_widget_at(widget.region.x, widget.region.y)[0] is widget
        assert compositor.get_widget_at(before.x, before.y)[0] is not widget


async def test_keyword_composites_override_components_in_authored_order():
    from textual.color import Color
    from textual.css.errors import StyleValueError

    app = App()
    async with app.run_test(size=(40, 12)) as pilot:
        widget = Label("composite content")
        await app.mount(widget)
        await pilot.pause()
        widget.set_styles(border=("solid", "red"), align=("left", "top"))
        updates = widget._inline_styles._updates
        widget.set_styles(border=("double", "blue"), align=("right", "bottom"))
        assert widget._inline_styles._updates == updates + 1
        assert widget.styles.align == ("right", "bottom")
        assert all(edge == ("double", Color.parse("blue")) for edge in widget.styles.border)
        widget.set_styles(border=("solid", "red"), border_top=("double", "green"))
        assert widget.styles.border_top == ("double", Color.parse("green"))
        assert widget.styles.border_bottom == ("solid", Color.parse("red"))
        widget.set_styles(border_top=("double", "green"), border=("solid", "red"))
        assert all(edge == ("solid", Color.parse("red")) for edge in widget.styles.border)
        before = widget._inline_styles.get_rules()
        updates = widget._inline_styles._updates
        with pytest.raises(StyleValueError):
            widget.set_styles(border=("double", "blue"), align=("right", "invalid"))
        assert widget._inline_styles.get_rules() == before
        assert widget._inline_styles._updates == updates
        widget.set_styles(border=None, align=("center", "middle"))
        assert not any(widget._inline_styles.has_rule(name) for name in
                       ("border_top", "border_right", "border_bottom", "border_left"))
        assert widget.styles.align == ("center", "middle")
        await pilot.pause()
        assert widget in app.screen._compositor.visible_widgets
