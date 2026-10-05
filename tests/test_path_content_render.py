"""Path policy consumes actual native widget style resources."""
import unittest

from textual.content import Content
from textual.geometry import Offset
from textual.selection import Selection
from textual.style import Style
from textual.visual import RenderOptions
from textual.widget import Widget

from toad.widgets.path_search import PathContent


class PathContentRenderTest(unittest.TestCase):
    def test_widget_styles_keep_path_policy_and_height_projection(self):
        widget = Widget()
        source = Content(
            "root/界/file.py\nsecond.txt\nthird.txt\nlast.txt"
        ).stylize(Style.parse("underline link='https://example.com'"))
        content = PathContent(source.plain, list(source.spans), source.cell_length)
        options = RenderOptions(
            widget._get_style,
            widget.styles,
            selection=Selection.from_offsets(Offset(2, 0), Offset(6, 2)),
            selection_style=Style.parse("reverse"),
            post_style=Style.parse("italic"),
        )
        base_style = Style.parse("white on black")
        for width in (9, 60):
            complete = content.render_strips(width, None, base_style, options)
            for height in (0, 1, 3, -1, None):
                with self.subTest(width=width, height=height):
                    bounded = content.render_strips(width, height, base_style, options)
                    expected = complete if height is None else complete[:height]
                    self.assertEqual(
                        [(strip.cell_length, list(strip)) for strip in bounded],
                        [(strip.cell_length, list(strip)) for strip in expected],
                    )
            self.assertIs(options.rules, widget.styles)
        self.assertEqual(content.render_strips(0, None, base_style, options), [])


if __name__ == "__main__":
    unittest.main()
