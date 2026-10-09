from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.geometry import Region
from textual.pilot import Pilot
from textual.widgets import Label


class ObservedScroll(VerticalScroll):
    coordinate_reads = 0

    @property
    def virtual_region_with_margin(self) -> Region:
        self.coordinate_reads += 1
        return super().virtual_region_with_margin


class NestedScrollApp(App[None]):
    CSS = """
    #outer { height: 10; border: solid green; }
    #inner { height: 15; margin: 1; border: solid blue; }
    Label { height: 3; }
    """

    def compose(self) -> ComposeResult:
        with ObservedScroll(id="outer"):
            with ObservedScroll(id="inner"):
                for index in range(12):
                    yield Label(f"Row {index}", id=f"row{index}")


async def test_nested_scroll_uses_one_parent_coordinate_per_step() -> None:
    app = NestedScrollApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await check_nested_scroll(app, pilot)


async def check_nested_scroll(app: NestedScrollApp, pilot: Pilot) -> None:
    outer = app.query_one("#outer", ObservedScroll)
    inner = app.query_one("#inner", ObservedScroll)
    target = app.query_one("#row11", Label)
    outer.coordinate_reads = inner.coordinate_reads = 0
    assert app.screen.scroll_to_widget(target, animate=False, immediate=True)
    assert (inner.coordinate_reads, outer.coordinate_reads) == (1, 1)
    await pilot.pause()
    assert inner.scroll_y > 0 and outer.scroll_y > 0
    assert target.region.intersection(inner.scrollable_content_region)
    assert target.region.intersection(outer.scrollable_content_region)
