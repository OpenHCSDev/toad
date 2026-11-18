"""The TUI offers the schemes drawn in the terminal's own colours: it asks its terminal for
their palette. Qt has no terminal, so it does not (tests/model/test_theme_offer.py)."""

from types import SimpleNamespace

from ui_theme.catalog import SCHEMES

from toad.textual_colours import TextualColours


def test_textual_offers_the_terminal_schemes_too():
    offered = TextualColours(SimpleNamespace()).schemes
    assert any(scheme.from_terminal for scheme in SCHEMES)
    assert {scheme.name for scheme in SCHEMES} <= offered.keys()
