from textual.content import Content
from textual.widgets import Static
from textual.app import App, ComposeResult
from textual.style import Style


async def test_content_property():
    static = Static()
    assert static.content == ""
    static.content = "Foo"
    assert static.content == "Foo"
    assert isinstance(static.content, str)
    assert static.visual == "Foo"
    assert isinstance(static.visual, Content)

    static.update("Hello")
    assert static.content == "Hello"
    assert isinstance(static.content, str)
    assert static.visual == "Hello"
    assert isinstance(static.visual, Content)


async def test_content_update_preserves_geometry_and_repaints_action_metadata():
    class ContentApp(App):
        accepted = False

        def compose(self) -> ComposeResult:
            yield Static(Content.styled("same names", "red"), id="names")

        def action_accept(self):
            self.accepted = True

    app = ContentApp()
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        names = app.query_one("#names", Static)
        names.auto_links = False
        revision = names._geometry_revision
        region = names.region
        replacement = Content.styled("same names", "green").stylize(
            Style.from_meta({"@click": "app.accept"})
        )
        names.update(replacement)
        assert not names._layout_required
        assert names._geometry_revision == revision
        await pilot.pause()
        assert names.region == region
        assert names.visual.is_same(replacement)
        style = app.screen._compositor.get_style_at(region.x, region.y)
        assert style.meta["@click"] == "app.accept"
        assert style.color.get_truecolor() == (0, 128, 0)
        await pilot.click(names, offset=(1, 0))
        assert app.accepted

        names.update(replacement, layout=True)
        assert names._geometry_revision > revision
        await pilot.pause()
        revision = names._geometry_revision
        names.update("new\nlines")
        assert names._geometry_revision > revision
        await pilot.pause()
        assert names.region.height == 2
        revision = names._geometry_revision
        names.update("explicit skip", layout=False)
        assert names._geometry_revision == revision


async def test_custom_measurement_and_setter_keep_layout_contract():
    class MeasuredStatic(Static):
        def get_content_height(self, container, viewport, width):
            return len(self.visual.spans) + 1

    class RenderedStatic(Static):
        def render(self):
            return super().render()

        def _render_styles_sensitive(self):
            # Style independence does not declare content measurement semantics.
            return False

    class VisualStatic(Static):
        @property
        def visual(self):
            return super().visual

    class CustomContent(Content):
        pass

    class SetterStatic(Static):
        def update(self, content="", *, layout=None):
            raise AssertionError("content setter must not invoke update override")

    for widget in (
        MeasuredStatic("same"), RenderedStatic("same"), VisualStatic("same"),
        Static(CustomContent("same")),
    ):
        assert widget.visual == "same"
        revision = widget._geometry_revision
        widget.update(Content.styled("same", "red"))
        assert widget._geometry_revision > revision
    widget = SetterStatic("same")
    assert widget.visual == "same"
    revision = widget._geometry_revision
    widget.content = "same"
    assert widget._geometry_revision > revision


async def test_container_update_keeps_layout():
    class ContainerStatic(Static):
        def compose(self):
            yield Static("child")

    class ContainerApp(App):
        def compose(self):
            yield ContainerStatic("same", id="parent")

    app = ContainerApp()
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        parent = app.query_one("#parent", ContainerStatic)
        assert parent.is_container
        revision = parent._geometry_revision
        parent.update(Content.styled("same", "red"))
        assert parent._geometry_revision > revision
