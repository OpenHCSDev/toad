"""Textual name waves repaint only when their terminal cells change."""

from toad.widgets.selection import ViewLabel


class RecordedViewLabel(ViewLabel):
    text_fades = ()

    def __init__(self, spans: list[tuple[int, int]]) -> None:
        super().__init__("busy")
        self.spans = iter(spans)
        self.repaints = 0

    def wave_running(self) -> bool:
        return True

    def wave_span(self) -> tuple[int, int]:
        return next(self.spans)

    def repaint_wave(self) -> None:
        self.repaints += 1


def test_textual_name_wave_skips_frames_covering_the_same_cells() -> None:
    label = RecordedViewLabel([(0, 2), (0, 2), (1, 3)])

    label.redraw()
    label.redraw()
    label.redraw()

    assert label.repaints == 2
