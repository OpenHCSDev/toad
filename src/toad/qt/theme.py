"""The colour schemes `ui.theme` names on Qt: the ones Textual's colours offer."""

from __future__ import annotations

from collections.abc import Mapping

from ui_theme.catalog import SCHEMES
from ui_theme.scheme import ColourScheme
from ui_theme.wal import WalFile


def offered_schemes(environment: Mapping[str, str]) -> dict[str, ColourScheme]:
    """ui_theme's catalog, and pywal's palette once pywal has written it, by name."""
    offered = {scheme.name: scheme for scheme in SCHEMES}
    wal = WalFile.directory(environment) / WalFile.NAME
    if wal.is_file():
        scheme = WalFile.read(wal).scheme
        offered[scheme.name] = scheme
    return offered


def current_scheme(environment: Mapping[str, str]) -> ColourScheme:
    """Toad's default theme: pywal's palette once pywal has written it, else Textual's dark.
    The window opens in it; the saved `ui.theme` is then applied with every other setting."""
    wal = WalFile.directory(environment) / WalFile.NAME
    return WalFile.read(wal).scheme if wal.is_file() else SCHEMES[0]
