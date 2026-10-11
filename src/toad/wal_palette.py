"""pywal's colour file, decoded once into a terminal palette.

pywal (`wal -i`, `wal -R`) writes `colors.json` in its cache directory and sends
the same colours to every open terminal as OSC 4/10/11 sequences, so ANSI
themes follow it without a repaint. A true-colour scheme reads the file
instead. The file format is pywal's; it is decoded exactly as written.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path

from agent_comms.field_codec import FieldCodec

from toad.colour_scheme import ColourScheme, Rgb, TerminalPalette


@dataclass(frozen=True)
class WalSpecial:
    background: Rgb
    foreground: Rgb
    cursor: Rgb


@dataclass(frozen=True)
class WalColours:
    color0: Rgb
    color1: Rgb
    color2: Rgb
    color3: Rgb
    color4: Rgb
    color5: Rgb
    color6: Rgb
    color7: Rgb
    color8: Rgb
    color9: Rgb
    color10: Rgb
    color11: Rgb
    color12: Rgb
    color13: Rgb
    color14: Rgb
    color15: Rgb


@dataclass(frozen=True)
class WalFile:
    """`colors.json` as pywal writes it."""

    wallpaper: str
    alpha: str
    special: WalSpecial
    colors: WalColours

    NAME = "colors.json"
    SCHEME = "wal"

    @staticmethod
    def directory(environment: Mapping[str, str]) -> Path:
        """pywal's cache directory: `PYWAL_CACHE_DIR`, else `~/.cache/wal`."""
        configured = environment.get("PYWAL_CACHE_DIR")
        return Path(configured) if configured else Path(environment["HOME"]) / ".cache" / "wal"

    @classmethod
    def read(cls, path: Path) -> WalFile:
        return FieldCodec.decode(cls, json.loads(path.read_text(encoding="utf-8")))

    @property
    def palette(self) -> TerminalPalette:
        special = self.special
        return TerminalPalette(special.background, special.foreground, special.cursor,
                               tuple(getattr(self.colors, slot.name) for slot in fields(WalColours)))

    @property
    def scheme(self) -> ColourScheme:
        return self.palette.scheme(self.SCHEME)

