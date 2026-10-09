from fractions import Fraction

import pytest

from textual.app import App
from textual.widget import NoScreen
from textual.widgets import Static


class ObservedAttachment(Static):
    attachment_reads = 0

    @property
    def is_attached(self) -> bool:
        self.attachment_reads += 1
        return super().is_attached


async def test_ordinary_box_measurement_does_not_acquire_mutation_attachment():
    app = App()
    async with app.run_test(size=(60, 20)) as pilot:
        widget = ObservedAttachment("native content")
        widget.styles.width = 20
        widget.styles.height = 3
        await app.mount(widget)
        await pilot.pause()
        widget.attachment_reads = 0
        boxes = [widget._get_box_model(app.size, app.size, Fraction(60), Fraction(20))
                 for _ in range(20)]
        assert widget.attachment_reads == 0
        assert all(box == boxes[0] for box in boxes)
        assert (boxes[0].width, boxes[0].height) == (20, 3)

        # NoScreen is the original unmounted boundary, not a refusal to measure
        # an ordinary authored box in this active application.
        detached = ObservedAttachment("not mounted")
        detached.styles.width = 7
        detached.styles.height = 2
        box = detached._get_box_model(app.size, app.size, Fraction(60), Fraction(20))
        assert (box.width, box.height) == (7, 2)


class RefusedScreen(ObservedAttachment):
    refuse_screen = False

    @property
    def screen(self):
        if self.refuse_screen:
            raise NoScreen("original custom source refused its screen")
        return super().screen


async def test_attached_custom_screen_refusal_is_not_unmounted_measurement():
    app = App()
    async with app.run_test() as pilot:
        widget = RefusedScreen("attached source")
        await app.mount(widget)
        await pilot.pause()
        widget.refuse_screen = True
        try:
            with pytest.raises(NoScreen, match="original custom source"):
                widget._get_box_model(app.size, app.size, Fraction(80), Fraction(24))
        finally:
            widget.refuse_screen = False
