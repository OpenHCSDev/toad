"""Reported patch hunks shared by live tools, saved tools and display styles."""

from dataclasses import dataclass
from collections.abc import Iterator
from itertools import zip_longest
import re

from rich.text import Text

from toad.line_blocks import LineBlock, LineRole, TextRole, AddedCodeRole, RemovedCodeRole

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class PatchCell:
    number: int
    text: str
    role: type[LineRole] = TextRole


@dataclass
class Patch(LineBlock):
    before_path: str
    after_path: str
    before: dict[int, str]
    after: dict[int, str]
    groups: list[list[tuple[str, int, int, int, int]]]

    @property
    def retained_bytes(self) -> int:
        return (128 + 4 * (len(self.before_path) + len(self.after_path))
                + sum(64 + 4 * len(text) for text in self.before.values())
                + sum(64 + 4 * len(text) for text in self.after.values())
                + sum(64 + 64 * len(group) for group in self.groups))

    @property
    def before_text(self) -> dict[int, Text]:
        return {number: Text(text.expandtabs(4)) for number, text in self.before.items()}

    @property
    def after_text(self) -> dict[int, Text]:
        return {number: Text(text.expandtabs(4)) for number, text in self.after.items()}

    @property
    def selection_text(self) -> str:
        return "\n".join((before or after).text for before, after in self.rows(False))

    @property
    def number_width(self) -> int:
        return len(str(max((*self.before, *self.after), default=0) + 1))

    def rows(self, split: bool) -> Iterator[tuple[PatchCell | None, PatchCell | None]]:
        for group in self.row_groups(split):
            yield from group

    def row_groups(self, split: bool) -> Iterator[tuple[tuple[PatchCell | None, PatchCell | None], ...]]:
        """Interpret the native diff opcodes in one place, preserving absolute lines."""
        for group in self.groups:
            rows = []
            for tag, i1, i2, j1, j2 in group:
                if tag == "equal":
                    rows.extend((PatchCell(i + 1, self.before[i]), PatchCell(j + 1, self.after[j]))
                                for i, j in zip(range(i1, i2), range(j1, j2)))
                else:
                    before = tuple(PatchCell(i + 1, self.before[i], RemovedCodeRole) for i in range(i1, i2))
                    after = tuple(PatchCell(j + 1, self.after[j], AddedCodeRole) for j in range(j1, j2))
                    if split:
                        rows.extend(zip_longest(before, after))
                    else:
                        rows.extend((cell, None) for cell in before)
                        rows.extend((None, cell) for cell in after)
            yield tuple(rows)

    @property
    def additions(self) -> int:
        return sum(j2 - j1 for group in self.groups for tag, _, _, j1, j2 in group if tag != "equal")

    @property
    def deletions(self) -> int:
        return sum(i2 - i1 for group in self.groups for tag, i1, i2, _, _ in group if tag != "equal")

    def require_changes(self) -> None:
        if not self.additions and not self.deletions:
            raise ValueError("Patch contains no changed lines")


def parse_patch(text: str) -> Patch:
    lines = text.splitlines()
    if len(lines) < 3 or not lines[0].startswith("--- ") or not lines[1].startswith("+++ "):
        raise ValueError("No unified patch headers")
    patch = Patch(lines[0][4:].split("\t")[0], lines[1][4:].split("\t")[0], {}, {}, [])
    index = 2
    while index < len(lines):
        match = _HUNK.match(lines[index])
        if not match:
            raise ValueError("Invalid patch hunk")
        old_start, old_count, new_start, new_count = match.groups()
        old, new = max(0, int(old_start) - 1), max(0, int(new_start) - 1)
        old_end, new_end = old + int(old_count or 1), new + int(new_count or 1)
        group = []
        run_kind = None
        run_old, run_new = old, new

        def flush():
            nonlocal run_old, run_new
            if old == run_old and new == run_new:
                return
            kind = ("equal" if run_kind == "equal" else
                    "replace" if old > run_old and new > run_new else
                    "delete" if old > run_old else "insert")
            group.append((kind, run_old, old, run_new, new))
            run_old, run_new = old, new

        index += 1
        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            index += 1
            if line.startswith("\\ No newline"):
                continue
            if not line or line[0] not in " +-":
                raise ValueError("Invalid hunk line")
            kind = "equal" if line[0] == " " else "change"
            if kind != run_kind:
                flush()
                run_kind = kind
            if line[0] in " -":
                patch.before[old] = line[1:]
                old += 1
            if line[0] in " +":
                patch.after[new] = line[1:]
                new += 1
            if old > old_end or new > new_end:
                raise ValueError("Patch hunk exceeds its declared range")
        flush()
        if old != old_end or new != new_end:
            raise ValueError("Incomplete patch hunk")
        patch.groups.append(group)
    patch.require_changes()
    return patch


def parse_numbered_patch(text: str) -> Patch:
    """Pi reports old coordinates for context/removals and new ones for additions.

    Every changed line is present. Ellipses omit unchanged lines only, so the
    displacement equals the sum of preceding additions and removals.
    """
    patch = Patch("", "", {}, {}, [])
    displacement = 0
    group = []
    for line in text.splitlines():
        match = re.fullmatch(r"([ +\-])\s*(\d+) (.*)", line)
        if match is None:
            if re.fullmatch(r" +\.\.\.", line):
                if group:
                    patch.groups.append(group)
                    group = []
                continue
            raise ValueError("Invalid numbered patch line")
        marker, number, content = match.groups()
        position = int(number) - 1
        if position < 0:
            raise ValueError("Numbered patch lines start at one")
        if marker == "+":
            old, new = position - displacement, position
            patch.after[new] = content
            displacement += 1
            opcode = ("insert", old, old, new, new + 1)
        elif marker == "-":
            old, new = position, position + displacement
            patch.before[old] = content
            displacement -= 1
            opcode = ("delete", old, old + 1, new, new)
        else:
            old, new = position, position + displacement
            patch.before[old] = patch.after[new] = content
            opcode = ("equal", old, old + 1, new, new + 1)
        if group and group[-1][2] == old and group[-1][4] == new:
            previous = group[-1]
            if (previous[0] == "equal") == (opcode[0] == "equal"):
                kind = ("equal" if opcode[0] == "equal" else
                        "replace" if opcode[2] > previous[1] and opcode[4] > previous[3] else
                        "delete" if opcode[2] > previous[1] else "insert")
                group[-1] = (kind, previous[1], opcode[2], previous[3], opcode[4])
                continue
        group.append(opcode)
    if group:
        patch.groups.append(group)
    patch.require_changes()
    return patch
