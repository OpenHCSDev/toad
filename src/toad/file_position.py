"""One-based file locations at the link boundary; native documents use zero-based cursors."""
from dataclasses import dataclass
import re
from typing import ClassVar


@dataclass(frozen=True)
class FilePosition:
    pattern: ClassVar[str] = r":(?P<line>[1-9]\d*)(?::(?P<column>[1-9]\d*))?"
    line: int
    column: int = 1

    def __post_init__(self):
        if self.line < 1 or self.column < 1:
            raise ValueError("File line and column must be positive")

    @classmethod
    def split(cls, value):
        match = re.fullmatch(r"(?P<path>.*?)" + cls.pattern, value)
        if not match:
            return value, None
        path, line, column = match.group("path", "line", "column")
        return path, cls(int(line), int(column or 1))

    @classmethod
    def from_fragment(cls, value):
        match = re.fullmatch(r"L([1-9]\d*)(?:C([1-9]\d*))?", value)
        return cls(int(match[1]), int(match[2] or 1)) if match else None

    @property
    def fragment(self):
        return f"L{self.line}C{self.column}"

    def reveal(self, area):
        area.move_cursor((self.line - 1, self.column - 1))
        area.focus()
