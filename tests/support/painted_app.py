"""Read the cells accepted by Toad's real display owner, including earlier frames."""

from functools import cached_property

from textual._compositor import ChopsUpdate, CompositorUpdate, LayoutUpdate
from textual.screen import Screen
from textual.strip import Strip
from toad.app import ToadApp


class PaintedApp(ToadApp):
    """Retain fixed-size test output, never a newly rendered scene."""

    @cached_property
    def _painted_screens(self) -> dict[Screen, list[Strip]]:
        return {}

    @cached_property
    def _painted_lines(self) -> set[str]:
        return set()

    def has_shown(self, text: str) -> bool:
        return any(text in line for line in self._painted_lines)

    def _display(self, screen, update):
        super()._display(screen, update)
        if not isinstance(update, CompositorUpdate) or not update.admitted:
            return
        width, height = screen.size
        rows = self._painted_screens.setdefault(screen, [Strip.blank(width) for _ in range(height)])

        def put(y: int, x: int, strip: Strip) -> None:
            previous = rows[y]
            rows[y] = Strip.join((previous.crop(0, x), strip,
                                  previous.crop(x + strip.cell_length, width)))

        # Decode the native output formats at their boundary. Reuse each
        # update's original strips/crops; asking the compositor to render
        # again could inspect a different, not-yet-accepted arrangement.
        if isinstance(update, LayoutUpdate):
            for y, line in enumerate(update.strips, update.region.y):
                put(y, update.region.x, Strip.join(line))
        elif isinstance(update, ChopsUpdate):
            for y, left, right in update.spans:
                for x, strip in update._get_line_chops(y, left, right):
                    put(y, x, strip)
        else:
            raise AssertionError(f"Unrecorded output format: {type(update).__name__}")
        self._painted_lines.update(row.text for row in rows)
