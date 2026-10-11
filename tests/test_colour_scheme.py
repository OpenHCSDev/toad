"""Colour schemes: pywal's file decoded once, colour depth decided once, role colours resolved per theme."""

import json
import subprocess
import sys

import pytest
from rich.style import Style
from textual.theme import BUILTIN_THEMES

from toad.colour_scheme import ColourDepth, Rgb, ThemeColour, TrueColourDepth
from toad.line_blocks import AgentRole, LineRole, MutedRole, ThinkingRole, UserRole
from toad.textual_colours import textual_theme
from toad.wal_palette import WalFile
from toad.widgets.transcript_lines import LineTheme

WAL = {
    "wallpaper": "/wallpapers/moss.jpg",
    "alpha": "100",
    "special": {"background": "#0b0b0d", "foreground": "#c3c3c3", "cursor": "#c3c3c3"},
    "colors": {f"color{index}": f"#{index:02x}{index:02x}{index:02x}" for index in range(16)},
}


def test_wal_file_decodes_to_a_scheme_from_ansi_slots(tmp_path):
    path = tmp_path / WalFile.NAME
    path.write_text(json.dumps(WAL))
    scheme = WalFile.read(path).scheme
    assert scheme.name == "wal" and scheme.dark
    assert scheme.background == Rgb(0x0b, 0x0b, 0x0d)
    assert (scheme.primary, scheme.secondary, scheme.error) == (
        Rgb(4, 4, 4), Rgb(6, 6, 6), Rgb(1, 1, 1))
    assert scheme.terminal.ansi[15] == Rgb(15, 15, 15)


def test_wal_file_rejects_what_pywal_does_not_write(tmp_path):
    path = tmp_path / WalFile.NAME
    path.write_text(json.dumps({**WAL, "checksum": "x"}))
    with pytest.raises(Exception):
        WalFile.read(path)
    path.write_text(json.dumps({**WAL, "special": {**WAL["special"], "cursor": "red"}}))
    with pytest.raises(ValueError):
        WalFile.read(path)


def test_wal_directory_honours_pywal_cache_dir():
    assert str(WalFile.directory({"HOME": "/h"})) == "/h/.cache/wal"
    assert str(WalFile.directory({"HOME": "/h", "PYWAL_CACHE_DIR": "/w"})) == "/w"


@pytest.mark.parametrize("environment, depth", [
    ({"TERM": "st-256color", "COLORTERM": "truecolor"}, "true_colour"),
    ({"TERM": "st-256color"}, "palette256"),
    ({"TERM": "xterm-direct"}, "true_colour"),
    ({"TERM": "linux"}, "ansi16"),
    ({"TERM": "dumb"}, "ansi16"),
])
def test_colour_depth_of_terminal(environment, depth):
    # terminfo is set up once per process, so each terminal is asked in its own.
    code = ("import json, sys; from toad.colour_scheme import ColourDepth; "
            "print(ColourDepth.of_terminal(json.loads(sys.argv[1])).declared_name)")
    result = subprocess.run([sys.executable, "-c", code, json.dumps(environment)],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == depth


def test_every_line_role_colour_is_resolved_by_every_theme():
    roles = [LineRole, *_subclasses(LineRole)]
    for theme in BUILTIN_THEMES.values():
        line_theme = LineTheme.of(theme.to_color_system().generate() | theme.variables)
        assert {colour for colour, _ in line_theme.colours} == set(ThemeColour.__registry__.values())
        for role in roles:
            assert isinstance(line_theme.style(role), Style)


def test_ansi_muted_text_is_dimmed_and_true_colour_muted_text_is_blended(tmp_path):
    ansi = BUILTIN_THEMES["ansi-dark"]
    ansi_lines = LineTheme.of(ansi.to_color_system().generate() | ansi.variables)
    assert ansi_lines.style(MutedRole).dim
    assert ansi_lines.style(ThinkingRole).dim and ansi_lines.style(ThinkingRole).italic
    path = tmp_path / WalFile.NAME
    path.write_text(json.dumps(WAL))
    wal = textual_theme(WalFile.read(path).scheme)
    wal_lines = LineTheme.of(wal.to_color_system().generate())
    assert not wal_lines.style(MutedRole).dim
    assert wal_lines.style(MutedRole).color.triplet is not None
    assert wal_lines.style(UserRole) != wal_lines.style(AgentRole)


def test_true_colour_depth_names_the_console_colour_system():
    assert TrueColourDepth.terminal_name == "truecolor"
    assert {depth.terminal_name for depth in ColourDepth.__registry__.values()} == {
        "truecolor", "256", "standard"}


def _subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)
