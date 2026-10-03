"""The existing Rich ANSI palette owns externally numbered colors."""

from rich.color import Color

ANSI_COLORS = tuple(Color.from_ansi(number) for number in range(256))
