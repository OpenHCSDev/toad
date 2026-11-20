"""Styled live rows request only the geometry their view owns."""

from rich.segment import Segment

from toad.widgets.line_markdown import LineMarkdown
from toad.widgets.tool_content import ToolContent
from toad.widgets.transcript_lines import PreparedLines


def test_wrapped_markdown_owns_height_while_horizontal_tool_output_also_owns_width() -> None:
    narrow = PreparedLines(20, ((Segment("one"),),))
    wide = PreparedLines(20, ((Segment("one longer line"),),))

    assert LineMarkdown().layout_extent(narrow) == LineMarkdown().layout_extent(wide)
    assert ToolContent().layout_extent(narrow) != ToolContent().layout_extent(wide)
