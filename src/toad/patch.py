"""Reported patch hunks shared by live tools, saved tools and display styles."""

import re
from abc import abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import chain, zip_longest
from typing import Annotated, ClassVar

from agent_comms.nominal.declared_choice import DeclaredChoice, TitledChoice
from python_introspect import AnnotatedDataclassValidationMixin, FieldLabel
from rich.text import Text

from toad.line_blocks import (
    AddedCodeRole,
    LineBlock,
    LineRole,
    RemovedCodeRole,
    TextRole,
)
from toad.setting_declarations import Effect, FamilyChoices

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchSide:
    """One side of a diff row: a numbered line, or no line on that side."""

    label = ""

    def selected(self) -> str:
        """The text copied from this side; a side with no line copies nothing."""
        return ""

    def otherwise(self, other: PatchSide) -> PatchSide:
        """The line a unified row shows: this side when it has one."""
        return self


@dataclass(frozen=True)
class PatchCell(PatchSide):
    """A numbered line with its displayed code, styled when the patch was."""

    number: int
    text: str
    code: Text
    role: type[LineRole] = TextRole

    @property
    def label(self) -> str:
        return str(self.number)

    def selected(self) -> str:
        return self.text


class NoPatchCell(PatchSide):
    """The side of a row where the other side's line was added or removed."""

    def otherwise(self, other: PatchSide) -> PatchSide:
        return other


NO_PATCH_CELL = NoPatchCell()


class PatchRows:
    """How a diff lays out its lines: before and after side by side, or one column."""

    split: ClassVar[bool]

    @abstractmethod
    def changed(self, before: tuple[PatchCell, ...], after: tuple[PatchCell, ...]) -> Iterable[tuple[PatchSide, PatchSide]]:
        """The rows of one changed run."""

    @abstractmethod
    def pane_width(self, width: int) -> int: ...

    @abstractmethod
    def number_columns(self, number_width: int) -> int:
        """Cells the line numbers take before the code."""


class SplitRows(PatchRows):
    """Removed lines beside the lines that replaced them."""

    split = True

    def changed(self, before, after):
        return zip_longest(before, after, fillvalue=NO_PATCH_CELL)

    def pane_width(self, width: int) -> int:
        return max(1, (width - 3) // 2)

    def number_columns(self, number_width: int) -> int:
        return number_width + 1


class UnifiedRows(PatchRows):
    """Removed lines above added ones, each row numbered for both files."""

    split = False

    def changed(self, before, after):
        return chain(((cell, NO_PATCH_CELL) for cell in before), ((NO_PATCH_CELL, cell) for cell in after))

    def pane_width(self, width: int) -> int:
        return max(1, width)

    def number_columns(self, number_width: int) -> int:
        return 2 * number_width + 2


SPLIT_ROWS, UNIFIED_ROWS = SplitRows(), UnifiedRows()


class DiffMarks:
    """The +/− column a diff gutter draws after the line numbers: shown, or not drawn."""

    width: ClassVar[int] = 0

    def prefix(self, role: type[LineRole]) -> str:
        return ""


class ShownDiffMarks(DiffMarks):
    width = 2

    def prefix(self, role: type[LineRole]) -> str:
        return role.diff_marker + " "


NO_MARKS, SHOWN_MARKS = DiffMarks(), ShownDiffMarks()


class DiffMode(DeclaredChoice, affix="Diff"):
    rows: ClassVar[PatchRows] = UNIFIED_ROWS
    auto_split = False

    @classmethod
    def rows_at(cls, width: int, required: int) -> PatchRows:
        return cls.rows


class UnifiedDiff(DiffMode):
    pass


class SplitDiff(DiffMode):
    rows = SPLIT_ROWS


class AutoDiff(TitledChoice, DiffMode):
    title = "Best fit"
    auto_split = True

    @classmethod
    def rows_at(cls, width: int, required: int) -> PatchRows:
        return SPLIT_ROWS if width >= required else UNIFIED_ROWS


class WrapMode(DeclaredChoice, affix="Mode"):
    enabled = False

    @classmethod
    def fitted_width(cls, available: int, content: int) -> int:
        return max(available, content)


class NoWrapMode(TitledChoice, WrapMode, declared_name="no-wrap"):
    title = "Don't wrap"


class WrapModeEnabled(TitledChoice, WrapMode, declared_name="wrap"):
    title = "Wrap long lines"
    enabled = True

    @classmethod
    def fitted_width(cls, available: int, content: int) -> int:
        return available


@dataclass(frozen=True)
class DiffSettings(AnnotatedDataclassValidationMixin):
    @Effect
    def changed(app, field) -> None:
        app.colours.refresh_line_renderer()
        app.theme_changed_signal.publish(app.current_theme)

    view: Annotated[
        type[DiffMode], FieldLabel("Display preference"), FamilyChoices(DiffMode), changed
    ] = AutoDiff
    annotations: Annotated[bool, FieldLabel("Show annotations (+/- symbols)?"), changed] = False
    wrap: Annotated[type[WrapMode], FieldLabel("Wrap code?"), FamilyChoices(WrapMode), changed] = NoWrapMode
    """If wrapping is disabled you can horizontal scroll with the trackpad or the mouse wheel plus shift."""

    @property
    def marks(self) -> DiffMarks:
        """The stored yes/no decoded once into what a diff gutter draws."""
        return (NO_MARKS, SHOWN_MARKS)[self.annotations]




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
        return "\n".join(before.otherwise(after).selected() for before, after in self.rows(UNIFIED_ROWS))

    @property
    def number_width(self) -> int:
        return len(str(max((*self.before, *self.after), default=0) + 1))

    def rows(self, layout: PatchRows) -> Iterator[tuple[PatchSide, PatchSide]]:
        for group in self.row_groups(layout):
            yield from group

    def row_groups(self, layout: PatchRows) -> Iterator[tuple[tuple[PatchSide, PatchSide], ...]]:
        """Interpret the native diff opcodes in one place, preserving absolute lines."""
        before_code, after_code = self.before_text, self.after_text
        for group in self.groups:
            rows = []
            for tag, i1, i2, j1, j2 in group:
                if tag == "equal":
                    rows.extend((PatchCell(i + 1, self.before[i], before_code[i]),
                                 PatchCell(j + 1, self.after[j], after_code[j]))
                                for i, j in zip(range(i1, i2), range(j1, j2)))
                else:
                    before = tuple(PatchCell(i + 1, self.before[i], before_code[i], RemovedCodeRole)
                                   for i in range(i1, i2))
                    after = tuple(PatchCell(j + 1, self.after[j], after_code[j], AddedCodeRole)
                                  for j in range(j1, j2))
                    rows.extend(layout.changed(before, after))
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
