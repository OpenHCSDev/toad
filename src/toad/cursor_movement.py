from __future__ import annotations

from dataclasses import dataclass

from textual.widgets.text_area import Selection


@dataclass(frozen=True)
class CursorMovement:
    previous: Selection
    current: Selection

    @property
    def moved_cursor(self) -> bool:
        return self.previous != self.current and self.current.is_empty

    @property
    def entered_slash(self) -> bool:
        return (self.previous.end, self.current.end) == ((0, 0), (0, 1))

    @property
    def retreating_first_line(self) -> bool:
        if (self.previous.end[0], self.current.end[0]) != (0, 0):
            return False
        return self.current.end[1] < self.previous.end[1]
