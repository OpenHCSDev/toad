"""A busy thread row repaints the line its name wave paints, not every line.

The name wave paints only the label line (ViewLabel.render_line, y == 0). A text fade
paints every line, so the whole row repaints only while a fade runs. Counting the
calls is the claim here: the wave keeps running, and the refresh covers its one line.
"""

from unittest.mock import PropertyMock, patch

from textual.geometry import Region, Size
from ui_theme.effects import NAME_WAVE, NEW_MESSAGE

from toad.widgets.comms_sidebar import ThreadStatusRow


def _row_with(effects: set) -> tuple[ThreadStatusRow, list, list]:
    row = ThreadStatusRow.__new__(ThreadStatusRow)
    row.effects = {effect: object() for effect in effects}
    refreshed: list = []
    repainted: list = []
    row.refresh = lambda *regions, **kwargs: refreshed.extend(regions)
    row.repaint_lines = lambda: repainted.append(True)
    return row, refreshed, repainted


def test_a_name_wave_alone_refreshes_only_the_label_line():
    row, refreshed, repainted = _row_with({NAME_WAVE})
    with patch.object(ThreadStatusRow, "size", new_callable=PropertyMock,
                      return_value=Size(40, 2)):
        row.redraw()
    assert refreshed == [Region(0, 0, 40, 1)], "only the label line is repainted"
    assert repainted == [], "the other lines are unchanged by the wave"
    assert NAME_WAVE in row.effects, "the wave itself keeps running"


def test_a_running_fade_repaints_every_line():
    row, refreshed, repainted = _row_with({NAME_WAVE, NEW_MESSAGE})
    row.redraw()
    assert repainted == [True], "a fade paints every line, so the row repaints whole"
    assert refreshed == [], "no partial refresh while a fade runs"


def test_an_idle_row_with_no_effect_repaints_through_the_base_path():
    row, refreshed, repainted = _row_with(set())
    row.redraw()
    assert repainted == [True]
    assert refreshed == []
