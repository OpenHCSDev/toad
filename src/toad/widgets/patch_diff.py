"""Render reported patch hunks with DiffView, without inventing omitted file text."""

from dataclasses import dataclass
import re

from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.text import Text
from textual.content import Content, Span
from textual.strip import Strip
from textual.style import Style
from textual.visual import Visual
from textual_diff_view import DiffView
from textual_diff_view._diff_view import DiffCode, LineAnnotations, LineContent

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Patch:
    before_path: str
    after_path: str
    before: dict[int, str]
    after: dict[int, str]
    groups: list[list[tuple[str, int, int, int, int]]]


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
    if not any(tag != "equal" for group in patch.groups for tag, *_ in group):
        raise ValueError("Patch contains no changed lines")
    return patch


# These are immutable semantic markers, not styles captured from a GUI/theme.
# Resolve them against the mounted view's component styles on publication.
_INLINE_ADDED = Style.from_meta({"toad_patch_inline": "added"})
_INLINE_REMOVED = Style.from_meta({"toad_patch_inline": "removed"})


@dataclass(frozen=True)
class PreparedPatch:
    theme: tuple[bool, bool]
    patch: Patch | None
    lines: tuple[dict[int, Content], dict[int, Content]] | None
    fallback: Text | None = None


def prepare_patch(text: str, ansi: bool, dark: bool) -> PreparedPatch:
    """Parse and highlight immutable text in a CPU worker, without a live app."""
    try:
        patch = parse_patch(text)
    except ValueError:
        from rich.syntax import Syntax

        highlighted = Syntax(
            text, "diff", theme="ansi_dark", background_color="default"
        ).highlight(text)
        # Keep Rich's ANSI colors symbolic. Conversion to Content belongs to
        # the UI's actual terminal palette, which is not present in this worker.
        return PreparedPatch((ansi, dark), None, None, highlighted)

    def highlight_lines(lines: dict[int, str], path: str) -> dict[int, Content]:
        code = "\n".join(value for _, value in sorted(lines.items())).expandtabs()
        styled = DiffView.highlight(code, path, "", ansi=ansi, dark=dark)
        highlighted = Content(code, list(styled.spans)).split("\n", allow_blank=True)
        return dict(zip(sorted(lines), highlighted))

    before = highlight_lines(patch.before, patch.before_path)
    after = highlight_lines(patch.after, patch.after_path)
    for group in patch.groups:
        for tag, i1, i2, j1, j2 in group:
            if tag == "replace" and i2 - i1 == j2 - j1:
                left, right = DiffView._highlight_diff_lines(
                    [before[i] for i in range(i1, i2)], [after[j] for j in range(j1, j2)],
                    _INLINE_ADDED, _INLINE_REMOVED,
                )
                before.update(zip(range(i1, i2), left))
                after.update(zip(range(j1, j2), right))
    return PreparedPatch((ansi, dark), patch, (before, after))


def _bind_inline_styles(lines: dict[int, Content], added: Style, removed: Style) -> "KnownLines":
    styles = {_INLINE_ADDED: added, _INLINE_REMOVED: removed}
    bound = {}
    for index, line in lines.items():
        spans = []
        changed = False
        for span in line.spans:
            replacement = styles.get(span.style)
            if replacement is None:
                spans.append(span)
            else:
                spans.append(Span(span.start, span.end, replacement))
                changed = True
        bound[index] = Content(line.plain, spans) if changed else line
    return KnownLines(bound)


class KnownLines(list[Content]):
    """Actual hunk lines with absolute-coordinate slices; no padded file prefix."""

    def __init__(self, lines: dict[int, Content]):
        super().__init__(value for _, value in sorted(lines.items()))
        self.positions = lines

    def __len__(self):
        return max(self.positions, default=-1) + 1

    def __getitem__(self, key):
        if isinstance(key, slice):
            return [self.positions[index] for index in range(
                key.start or 0, key.stop if key.stop is not None else len(self), key.step or 1
            )]
        return self.positions[key]


class _DiffRow(LineContent):
    """One native nonwrapping row, retaining its hunk-relative coordinates.

    Keep the segment construction in sync with LineContent.render_strips. The
    original visual remains on DiffCode for measurement and copy extraction.
    """

    def __init__(self, source: LineContent, y: int):
        self.source = source
        self.y = y

    def render_strips(self, width, height, style, options):
        source, y = self.source, self.y
        line = source.code_lines[y]
        if line is None:
            line = Content.styled(
                "╲" * width, "" if source._hatch_style is None else source._hatch_style
            )
        else:
            if options.selection is not None:
                if span := options.selection.get_span(y):
                    start, end = span
                    if end == -1:
                        end = len(line)
                    line = line.stylize(options.selection_style or Style.null(), start, end)
            if line.cell_length < width:
                line = line.pad_right(width - line.cell_length)
        line = line.stylize_before(source.line_styles[y]).stylize_before(style)
        segments = []
        x = 0
        for text, rich_style, _ in line.render_segments():
            if rich_style is not None:
                rich_style = rich_style + RichStyle.from_meta({"offset": (x, y)})
            segments.append(Segment(text, rich_style))
            x += len(text)
        return [Strip(segments, line.cell_length)]


class PatchDiffCode(DiffCode):
    """Let Textual's styles cache request only damaged/visible hunk rows."""

    def render_line(self, y: int) -> Strip:
        visual = self._render()
        # Folded visuals and alignment require the native whole-visual layout.
        if type(visual) is not LineContent or self.styles.content_align != ("left", "top"):
            return super().render_line(y)
        if self.BLANK or not 0 <= y < min(len(visual.code_lines), len(visual.line_styles)):
            return Strip.blank(self.size.width, self.visual_style.rich_style)
        return Visual.to_strips(
            self, _DiffRow(visual, y), self.size.width, 1, self.visual_style
        )[0]


class _PatchLineAnnotations(LineAnnotations):
    """Composition-owned immutable number lists need only one width scan."""

    def watch_numbers(self) -> None:
        self._number_width = None

    @property
    def number_width(self) -> int:
        if getattr(self, "_number_width", None) is None:
            self._number_width = super().number_width
        return self._number_width


class PatchDiffView(DiffView):
    """Reuse DiffView's split/unified rendering with exact native hunk opcodes."""

    def __init__(self, patch: Patch, *, prepared: PreparedPatch | None = None, **kwargs):
        self.patch = patch
        self._prepared = prepared
        super().__init__(patch.before_path, patch.after_path, "", "", **kwargs)

    def _prepared_theme_matches(self) -> bool:
        theme = self.app.current_theme
        return self._prepared is None or self._prepared.theme == (theme.ansi, theme.dark)

    def _check_auto_split(self, width: int):
        if self._prepared_theme_matches():
            super()._check_auto_split(width)

    def compose(self):
        if not self._prepared_theme_matches():
            from textual.widgets import Static

            # The owning ToolCallDiff is preparing the new syntax palette.
            yield Static("Preparing diff…")
            return
        # The dependency yields leaves while its container context managers are
        # active. Substitute only those leaves, preserving the native hierarchy,
        # CSS type selectors, scroll links, and all opcode/style construction.
        for widget in super().compose():
            if type(widget) is DiffCode:
                yield PatchDiffCode(widget.render())
            elif type(widget) is LineAnnotations:
                yield _PatchLineAnnotations(widget.numbers)
            else:
                yield widget

    @property
    def grouped_opcodes(self):
        return self.patch.groups

    @property
    def highlighted_code_lines(self):
        if self._highlighted_code_lines is None:
            if self._prepared is not None:
                assert self._prepared_theme_matches()
                assert self._prepared.lines is not None
                added = self.get_visual_style("diff-view--inline-added")
                removed = self.get_visual_style("diff-view--inline-removed")
                self._highlighted_code_lines = tuple(
                    _bind_inline_styles(lines, added, removed) for lines in self._prepared.lines
                )
                return self._highlighted_code_lines
            def highlight_lines(lines, path):
                code = "\n".join(value for _, value in sorted(lines.items())).expandtabs()
                styled = self.highlight(code, path, "", ansi=self.app.current_theme.ansi,
                                        dark=self.app.current_theme.dark)
                # The highlighter normalizes trailing newlines. Preserve the
                # exact known source lines (including blank context at EOF)
                # and use only its styles; otherwise absolute hunk keys vanish.
                highlighted = Content(code, list(styled.spans)).split("\n", allow_blank=True)
                return dict(zip(sorted(lines), highlighted))

            before = highlight_lines(self.patch.before, self.patch.before_path)
            after = highlight_lines(self.patch.after, self.patch.after_path)
            for group in self.patch.groups:
                for tag, i1, i2, j1, j2 in group:
                    if tag == "replace" and i2 - i1 == j2 - j1:
                        left, right = self._highlight_diff_lines(
                            [before[i] for i in range(i1, i2)], [after[j] for j in range(j1, j2)],
                            self.get_visual_style("diff-view--inline-added"),
                            self.get_visual_style("diff-view--inline-removed"),
                        )
                        before.update(zip(range(i1, i2), left))
                        after.update(zip(range(j1, j2), right))
            self._highlighted_code_lines = KnownLines(before), KnownLines(after)
        return self._highlighted_code_lines
