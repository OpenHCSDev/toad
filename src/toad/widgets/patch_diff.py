"""Render reported patch hunks with DiffView, without inventing omitted file text."""

from dataclasses import dataclass
from functools import cached_property
import re

from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.text import Text
from textual.content import Content, Span
from textual.geometry import Region
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, Visual
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
class DiffStyleRun:
    start: int
    end: int
    styles: tuple[Style | str, ...]


class PreparedDiffLine(Content):
    """Native copy/wrap Content plus worker-prepared, ordered style intervals."""

    def __init__(self, line: Content, runs: tuple[DiffStyleRun, ...], terminal_boundary: bool):
        super().__init__(line.plain, list(line.spans), line.cell_length)
        self.runs = runs
        self.terminal_boundary = terminal_boundary


def prepare_diff_line(line: Content) -> Content:
    """Do the native span sweep once, before a mounted row needs to paint.

    Keep ordered styles rather than blending them here: alpha/background
    composition must include the UI's actual base style in native order.
    Unusual external spans retain the ordinary Content rendering path.
    """
    spans = line.spans
    length = len(line)
    if any(not 0 <= span.start < span.end <= length for span in spans):
        return line
    events = [(0, False, -1), (length, True, -1)]
    events.extend((span.start, False, index) for index, span in enumerate(spans))
    events.extend((span.end, True, index) for index, span in enumerate(spans))
    events.sort(key=lambda event: (event[0], event[1]))
    active: set[int] = set()
    runs = []
    for (offset, leaving, index), (end, _, _) in zip(events, events[1:]):
        if leaving:
            active.remove(index)
        else:
            active.add(index)
        if end > offset:
            runs.append(DiffStyleRun(offset, end, tuple(spans[index].style for index in sorted(active) if index >= 0)))
    return PreparedDiffLine(line, tuple(runs), any(span.end == length for span in spans))


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
    return PreparedPatch((ansi, dark), patch, (
        {index: prepare_diff_line(line) for index, line in before.items()},
        {index: prepare_diff_line(line) for index, line in after.items()},
    ))


def _bind_inline_styles(lines: dict[int, Content], added: Style, removed: Style) -> "KnownLines":
    styles = {_INLINE_ADDED: added, _INLINE_REMOVED: removed}
    bound: dict[int, Content] = {}
    for index, line in lines.items():
        spans = []
        changed = False
        for span in line.spans:
            replacement = styles.get(span.style) if isinstance(span.style, Style) else None
            if replacement is None:
                spans.append(span)
            else:
                spans.append(Span(span.start, span.end, replacement))
                changed = True
        if changed and isinstance(line, PreparedDiffLine):
            runs = tuple(DiffStyleRun(run.start, run.end, tuple(
                styles.get(style, style) if isinstance(style, Style) else style for style in run.styles))
                         for run in line.runs)
            bound[index] = PreparedDiffLine(Content(line.plain, spans), runs, line.terminal_boundary)
        else:
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
        self.line = source.code_lines[y]

    def render_strips(self, width, height, style, options):
        source, y = self.source, self.y
        line = self.line
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
        line = line.stylize_before(source.line_styles[y])
        segments = []
        x = 0
        # A base style has the same precedence as the full-length prefix span,
        # without copying Content or sorting that extra pair of span events.
        # Empty width-zero rows had no prefix span in the native visual.
        for text, rich_style, _ in line.render_segments(style if len(line) else Style.null()):
            if rich_style is not None:
                rich_style = rich_style + RichStyle.from_meta({"offset": (x, y)})
            segments.append(Segment(text, rich_style))
            x += len(text)
        return [Strip(segments, line.cell_length)]


@dataclass
class _DiffPaint:
    """One synchronous native paint; never retained across UI state changes."""

    code: "PatchDiffCode"
    source: LineContent

    @cached_property
    def styles(self) -> dict[tuple[Style | str, ...], RichStyle | None]:
        return {}

    def rich_style(self, styles: tuple[Style | str, ...]) -> RichStyle | None:
        if styles not in self.styles:
            combined = self.style
            for style in styles:
                if isinstance(style, str):
                    try:
                        style = Style.parse(style)
                    except Exception:
                        # Content.render treats an unparseable span as null.
                        style = Style.null()
                combined += style
            rich_style = combined.rich_style if combined else None
            link_style = self.link_style
            if (rich_style is not None and link_style is not None
                    and rich_style._meta is not None and "@click" in rich_style.meta):
                rich_style += link_style
            self.styles[styles] = rich_style
        return self.styles[styles]

    @cached_property
    def width(self) -> int:
        return self.code.size.width

    @cached_property
    def style(self) -> Style:
        return self.code.visual_style

    @cached_property
    def options(self) -> RenderOptions:
        code = self.code
        selection = code.text_selection
        selection_style = (
            Style.from_styles(code.screen.get_component_styles("screen--selection"))
            if selection is not None else None
        )
        return RenderOptions(code._get_style, code.styles.get_rules(), selection, selection_style)

    @cached_property
    def link_style(self) -> RichStyle | None:
        code = self.code
        return (code.link_style if code.auto_links and not code.is_container
                and not code.screen._selecting else None)

    def row(self, y: int) -> Strip:
        row = _DiffRow(self.source, y)
        line = row.line
        link_style = self.link_style
        if isinstance(line, PreparedDiffLine) and (link_style is None or link_style._meta is None):
            # Native link presentation has no metadata. Apply it once per
            # style before adding row offsets, instead of rebuilding every
            # Segment and unpickling its new selection offset just to ask
            # whether it contains a click action.
            return self.prepared_row(line, y)
        strip = row.render_strips(self.width, 1, self.style, self.options)[0]
        return strip if link_style is None else strip._apply_link_style(link_style)

    def prepared_row(self, line: PreparedDiffLine, y: int) -> Strip:
        """Apply only paint-time base/selection styles to prepared intervals."""
        length = len(line)
        text = line.plain
        padding = max(0, self.width - line.cell_length)
        runs = line.runs
        if padding:
            text += " " * padding
            if runs and not line.terminal_boundary:
                runs = (*runs[:-1], DiffStyleRun(runs[-1].start, length + padding, runs[-1].styles))
            else:
                runs = (*runs, DiffStyleRun(length, length + padding, ()))

        options = self.options
        span = options.selection.get_span(y) if options.selection is not None else None
        start = end = 0
        if span and options.selection_style:
            start, end = span
            if end == -1:
                end = length
            if start < 0:
                start += length
            if end < 0:
                end += length
            if start < 0 or end < 0:
                strip = _DiffRow(self.source, y).render_strips(self.width, 1, self.style, options)[0]
                link_style = self.link_style
                return strip if link_style is None else strip._apply_link_style(link_style)
            end = min(end, length)
            if start >= length or end <= start:
                start = end = 0
        base = (self.source.line_styles[y],)
        segments = []
        for run in runs:
            boundaries = [run.start]
            boundaries.extend(value for value in (start, end) if run.start < value < run.end)
            boundaries.append(run.end)
            for left, right in zip(boundaries, boundaries[1:]):
                selected = start <= left < end
                styles = base + run.styles
                if selected and options.selection_style is not None:
                    styles += (options.selection_style,)
                rich_style = self.rich_style(styles)
                if rich_style is not None:
                    rich_style += RichStyle.from_meta({"offset": (left, y)})
                segments.append(Segment(text[left:right], rich_style))
        if not runs:
            segments.append(Segment("", None))
        return Strip(segments, line.cell_length + padding)


class PatchDiffCode(DiffCode):
    """Let Textual's styles cache request only damaged/visible hunk rows."""

    _paint: _DiffPaint | None = None

    def render_lines(self, crop: Region) -> list[Strip]:
        visual = self._render()
        if type(visual) is not LineContent or self.styles.content_align != ("left", "top"):
            return super().render_lines(crop)
        # Selection, native link style and geometry remain constant during this
        # synchronous crop. Resolving them for every code line repeats ancestor
        # walks and style composition. A paint-local context also leaves cached
        # rows lazy and is discarded before resize/theme/selection can change.
        previous = self._paint
        self._paint = _DiffPaint(self, visual)
        try:
            return super().render_lines(crop)
        finally:
            self._paint = previous

    def render_line(self, y: int) -> Strip:
        if paint := self._paint:
            if self.BLANK or not 0 <= y < min(len(paint.source.code_lines), len(paint.source.line_styles)):
                return Strip.blank(paint.width, paint.style.rich_style)
            return paint.row(y)
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

    _number_width: int | None = None

    def watch_numbers(self) -> None:
        self._number_width = None

    @property
    def number_width(self) -> int:
        width = self._number_width
        if width is None:
            width = self._number_width = super().number_width
        return width


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
