"""Qt offers only the colour schemes it can draw.

A scheme drawn in the terminal's own colours (`ColourScheme.from_terminal`) needs a terminal
that answers its palette: the TUI asks its terminal, Qt has none. A saved `ui.theme` naming
one stopped the phone app at every launch (2026-11-18), so Qt must never offer one.
"""

from ui_theme.catalog import SCHEMES

from toad.qt.theme import offered_schemes


def test_qt_offers_only_schemes_it_can_draw(tmp_path):
    offered = offered_schemes({"HOME": str(tmp_path), "XDG_CACHE_HOME": str(tmp_path)})
    terminal = {scheme.name for scheme in SCHEMES if scheme.from_terminal}
    assert terminal, "the catalog has schemes in the terminal's own colours"
    assert not terminal & offered.keys()
    assert {scheme.name for scheme in SCHEMES if not scheme.from_terminal} <= offered.keys()
    for scheme in offered.values():
        for colour in scheme.resolved_colours:
            colour.rgb(scheme)

