"""A name wave repaints its line only when its band reaches other cells, in each frontend."""

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


class RecordedTabBar:
    """What a tab title's wave asks of its bar: the band's cells, and to paint its tab."""

    def __init__(self, spans: list[tuple[int, int]]) -> None:
        from ui_theme.clock import AnimationClock

        self.clock = AnimationClock(lambda interval: None)
        self.spans = iter(spans)
        self.repainted: list[str] = []

    def isVisible(self) -> bool:
        return True

    def wave_span(self, wave) -> tuple[int, int]:
        return next(self.spans)

    def repaint_tab(self, mode: str) -> None:
        self.repainted.append(mode)


def test_qt_tab_title_wave_paints_its_own_tab_when_the_band_reaches_other_cells() -> None:
    """The same shared step as every waving line (`NameWave.wave_frame_drawn`): the tab
    title painted the whole tab bar on each frame of the clock."""
    from toad.qt.name_wave import QtTabWave

    bar = RecordedTabBar([(0, 2), (0, 2), (1, 3)])
    wave = QtTabWave(bar, "claude-a")
    wave.start_wave()

    for _frame in range(3):
        wave.repaint()

    assert bar.repainted == ["claude-a", "claude-a"]
    wave.stop_wave()
    assert bar.repainted == ["claude-a"] * 3  # the idle title, once
