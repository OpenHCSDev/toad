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
        from toad.qt.widget_animation import QtAnimationClock

        self.clock = QtAnimationClock(lambda interval: None)
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


def test_qt_name_wave_delegate_caches_band_inks_and_queries_row_once_per_paint() -> None:
    """Painting a waving sidebar row draws the accent band at its moving cell span while
    reusing cached FormatRanges and checking wave_running only once per paint."""
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem
    from pyqt_reactive.widgets.shared.list_item_delegate import LAYOUT_ROLE
    from pyqt_reactive.widgets.shared.styled_text_layout import Segment, StyledTextLayout

    from toad.qt.name_wave import QtNameWaveDelegate

    app = QApplication.instance() or QApplication([])
    tree = QTreeWidget()
    tree.setColumnCount(1)
    accent = QColor(255, 80, 0)
    delegate = QtNameWaveDelegate(
        accent, QColor("#eeeeee"), QColor("#888888"), QColor("#ffffff"), tree,
    )
    tree.setItemDelegateForColumn(0, delegate)

    class WavingItem(QTreeWidgetItem):
        def __init__(self) -> None:
            super().__init__()
            self.animation: object | None = object()
            self.painted_span: tuple[int, int] | None = (0, 3)

        def band_drawn(self) -> tuple[int, int] | None:
            return self.painted_span

    item = WavingItem()
    item.setData(0, LAYOUT_ROLE, StyledTextLayout(name=Segment("MMMMMMMMMMMMMMMM"), multiline=True))
    tree.addTopLevelItem(item)
    tree.resize(300, 120)
    tree.show()
    app.processEvents()

    option = QStyleOptionViewItem()
    option.initFrom(tree)
    option.rect = tree.visualRect(tree.indexFromItem(item, 0))

    def paint_accent_xs() -> list[int]:
        image = QImage(tree.viewport().size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("black"))
        painter = QPainter(image)
        delegate.paint(painter, option, tree.model().index(0, 0))
        painter.end()
        return [x for x in range(image.width())
                if any(image.pixelColor(x, y) == accent for y in range(option.rect.top(), option.rect.bottom()))]

    left = paint_accent_xs()
    assert len(delegate._row_images) == 1
    assert len(delegate.bold) == 1
    first_bold = next(iter(delegate.bold.values()))[1]
    assert first_bold.paragraphs[0].cacheEnabled() is True
    paint_accent_xs()
    assert next(iter(delegate.bold.values()))[1] is first_bold
    item.painted_span = (8, 11)
    right = paint_accent_xs()
    assert left and right and max(left) < min(right)

    # Updating a sibling row drops only that sibling's cached QImage bucket, keeping item's intact.
    sibling = WavingItem()
    sibling.setData(0, LAYOUT_ROLE, StyledTextLayout(name=Segment("NNNNNNNNNNNNNNNN"), multiline=True))
    tree.addTopLevelItem(sibling)
    app.processEvents()
    sib_opt = QStyleOptionViewItem()
    sib_opt.initFrom(tree)
    sib_opt.rect = tree.visualRect(tree.indexFromItem(sibling, 0))
    img = QImage(tree.viewport().size(), QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    delegate.paint(painter, option, tree.model().index(0, 0))
    delegate.paint(painter, sib_opt, tree.model().index(1, 0))
    painter.end()
    kept_item_row = delegate.prepared_row(tree.model().index(0, 0))
    kept_sib_row = delegate.prepared_row(tree.model().index(1, 0))
    assert id(kept_item_row) in delegate._row_images
    assert id(kept_sib_row) in delegate._row_images
    sibling.setData(0, LAYOUT_ROLE, StyledTextLayout(name=Segment("PPPPPPPPPPPPPPPP"), multiline=True))
    assert id(kept_item_row) in delegate._row_images
    assert id(kept_sib_row) not in delegate._row_images

    # Idle (running=False, span=None) and bold waving between bands (running=True, span=None)
    # must stay distinct in `_row_images`.
    item.painted_span = None
    p2 = QPainter(img)
    delegate.paint(p2, option, tree.model().index(0, 0))
    p2.end()
    before_variants = len(delegate._row_images[id(kept_item_row)][1])
    item.animation = None
    p3 = QPainter(img)
    delegate.paint(p3, option, tree.model().index(0, 0))
    p3.end()
    assert len(delegate._row_images[id(kept_item_row)][1]) == before_variants + 1

    from toad.qt.name_wave import QtSessionTabBar
    from toad.qt.widget_animation import QtAnimationClock

    bar = QtSessionTabBar(QtAnimationClock(lambda _dt: None), accent, QColor("#eeeeee"))
    try:
        layout = bar.bold_line("toad-qt", 120)
        assert layout.cacheEnabled() is True
        baked = bar.baked_band_layout(layout, (1, 4))
        assert baked.cacheEnabled() is True
        assert bar.baked_band_layout(layout, (1, 4)) is baked
        bar.set_colours(QColor("#00ff00"), QColor("#ffffff"))
        assert bar._banded == {}
    finally:
        bar.deleteLater()
