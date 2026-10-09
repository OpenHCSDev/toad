from textual import containers, widgets
from textual.app import App, ComposeResult
from textual.layouts.grid import GridLayout


async def test_grid_size():
    """Test the `grid_size` property on GridLayout."""

    class GridApp(App):
        CSS = """
        Grid {
            grid-size: 3;
            grid-columns: auto;
            height: auto;
            Label {
                padding: 2 4;
                border: blue;
            }
        }
        """

        def compose(self) -> ComposeResult:
            with containers.VerticalScroll():
                with containers.Grid():
                    for _ in range(7):
                        yield widgets.Label("Hello, World!")

    app = GridApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.wait_for_refresh()
        grid_layout = app.query_one(containers.Grid).layout
        assert isinstance(grid_layout, GridLayout)
        assert grid_layout.grid_size == (3, 3)


async def test_acquire_configured_grid_keeps_inputs_and_owns_new_geometry():
    class ConfiguredGridApp(App):
        def compose(self) -> ComposeResult:
            with containers.Grid(id="grid"):
                yield widgets.Label("First")
                yield widgets.Label("Second")

    app = ConfiguredGridApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        original = app.query_one("#grid").layout
        assert isinstance(original, GridLayout)
        assert original.grid_size is not None
        original.min_column_width = 3
        original.max_column_width = 7
        original.stretch_height = True
        original.regular = True
        original.expand = True
        original.shrink = True
        original.auto_minimum = True
        last_grid_size = original.grid_size
        acquired = original.acquire_document()
        assert acquired is not original
        assert type(acquired) is type(original)
        assert acquired.document_key() == original.document_key()
        assert acquired.grid_size is None
        assert original.grid_size == last_grid_size
