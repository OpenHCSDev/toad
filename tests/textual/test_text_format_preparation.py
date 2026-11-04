"""Detached native rendering retains the actual acquired formatting policy."""

import pickle
from functools import partial

import pytest
from rich.console import Console
from rich.style import Style as RichStyle
from textual.content import Content
from textual.style import Style
from textual.text_format import TextFormatSnapshot
from textual.visual import RenderOptions

from toad.colour_ink import TRUE_COLOUR_INK
from toad.widgets.path_search import PathContent
from toad.render_tasks import RichRenderTask
from toad.rich_preparation import ContentSource, RichPresentation, SyntaxPalette


@pytest.mark.parametrize("formatting", [
    TextFormatSnapshot("start", "wrap", "fold", 0),
    TextFormatSnapshot("right", "nowrap", "ellipsis", 1),
    TextFormatSnapshot("left", "nowrap", "clip", 2),
])
@pytest.mark.parametrize("auto_width", [False, True])
def test_detached_native_task_retains_formatting(
    formatting: TextFormatSnapshot, auto_width: bool,
) -> None:
    content = Content("one two three 界\nsecond source line")
    presentation = RichPresentation(
        Console(width=8).options, RichStyle(), None, auto_width,
        None, "truecolor", SyntaxPalette(TRUE_COLOUR_INK, True), text_format=formatting,
    )
    task = pickle.loads(pickle.dumps(RichRenderTask(ContentSource(content), presentation)))
    prepared = task.execute()
    width = (max(1, min(8, content.get_optimal_width(formatting, 8)))
             if auto_width else 8)
    expected = content.render_strips(
        width, None, Style(), RenderOptions(Style.parse, formatting)
    )
    assert task.presentation.text_format == formatting
    assert prepared.width == width
    assert [list(line) for line in prepared.lines] == [list(line) for line in expected]
    assert prepared.selection_text == content.plain


def test_path_content_uses_its_clipped_policy_for_measurement_and_paint() -> None:
    content = PathContent("top/nested/file.py")
    supplied = TextFormatSnapshot("right", "wrap", "fold", 2)
    painted = content.render_strips(
        8, None, Style(), RenderOptions(
            partial(Style.parse, variables={"text-error": "red"}), supplied
        ),
    )
    assert content.get_height(supplied, 8) == len(painted) == 1
    assert content.get_optimal_width(supplied, 8) == content.cell_length
    assert content.get_minimal_width(supplied) == content.cell_length
    assert painted[0].text.startswith("⋯ ")
