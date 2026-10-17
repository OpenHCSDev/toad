"""Textual-facing: a transcript page widget counts rows at layout and builds strips only when Textual draws a row.

A transcript page laid out at a new width builds no rows; drawing a row builds only its fragment's."""

from types import SimpleNamespace
import unittest

from agent_comms.transcript_events import AssistantTranscript, UserTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from textual._context import active_app
from textual.app import App
from textual.selection import Selection

from toad.widgets.transcript_history import TranscriptPageView
from toad.line_blocks import AgentRole, Body, Divider, Gap, Summary, UserRole
from toad.widgets.transcript_lines import LineTheme, PlainLines


def page_view(count: int) -> TranscriptPageView:
    cursor = TranscriptCursor("fixture", 1)
    events = tuple(
        (UserTranscript if index % 3 == 0 else AssistantTranscript)(
            f"Message {index} " + "word " * (index % 40) + "\n\n- item\n- another item")
        for index in range(count))
    return TranscriptPageView(TranscriptPage(events, cursor, cursor, False, False), batch_size=count)


class TranscriptPageWidth(unittest.TestCase):
    def setUp(self):
        app = App()
        theme = LineTheme.of(app.get_css_variables(), "truecolor", app.ansi_theme)
        # An app that is not running: the page stays detached and starts no renderer.
        self.reset = active_app.set(SimpleNamespace(colours=SimpleNamespace(line_theme=theme), _exit=True))

    def tearDown(self):
        active_app.reset(self.reset)

    def test_width_change_counts_rows_without_building_strips(self):
        view = page_view(60)
        for width in (100, 63, 100):
            height = view.get_content_height(None, None, width)
            lines = [lines for _fragment, _first, lines in view._layout]
            self.assertEqual(len(lines), len(view.fragments_in_range))
            self.assertEqual(height, sum(item.height for item in lines))
            self.assertTrue(all(item.width == width for item in lines))
            self.assertFalse(any("strips" in vars(item) or "rows" in vars(item) for item in lines),
                             "layout builds no rows or strips")
            # Drawing one row builds that fragment's strips only, at the laid-out width.
            fragment, first, drawn = view._layout[len(lines) // 2]
            row = view.render_line(first)
            self.assertEqual(row, drawn.strips_at(fragment.link_place)[0])
            self.assertEqual(row.cell_length, width)
            self.assertEqual([item for item in lines if "strips" in vars(item)], [drawn])
            # Every row of the page draws at exactly the width, and each
            # fragment's counted height is the number of rows it draws.
            self.assertTrue(all(view.render_line(y).cell_length == width for y in range(height)))
            self.assertTrue(all(item.height == len(item.rows) for item in lines))
            for item in lines:
                vars(item).pop("strips", None)
                vars(item).pop("rows", None)

    def test_selected_text_is_the_text_the_page_draws(self):
        view = page_view(3)
        view.get_content_height(None, None, 80)
        text, ending = view.get_selection(Selection(None, None))
        self.assertIn("Message 0", text)
        self.assertIn("Message 2", text)
        self.assertEqual(ending, "\n")

    def test_filtered_page_lays_out_only_shown_fragments(self):
        from toad.widgets.message_filter import all_categories, event_category

        view = page_view(60)
        user = event_category(view.fragments_in_range[0].events[0])
        view.visible_categories = all_categories() - {user}
        shown = [fragment for fragment in view.fragments_in_range
                 if any(event_category(event) != user for event in fragment.events)]
        view.get_content_height(None, None, 80)
        self.assertEqual([fragment for fragment, _first, _lines in view._layout], shown)
        self.assertLess(len(shown), len(view.fragments_in_range))

    def test_plain_height_counts_the_rows_plain_mode_draws(self):
        theme = active_app.get().colours.line_theme
        blocks = (
            Divider.titled("Agent", AgentRole), Summary("· Agent activity"), Gap(),
            Body("", role=UserRole), Body("\t\tindented\tline", role=AgentRole),
            Body("x" * 250 + "\n\n" + "short\n" + "y" * 77, role=AgentRole, bar=UserRole),
            Body("# Heading\n\n- item " * 30, role=AgentRole, markdown=True),
        )
        for width in (1, 2, 3, 20, 77, 78, 79, 140):
            lines = PlainLines(width, theme, blocks)
            self.assertEqual(lines.height, len(lines.rows), width)


if __name__ == "__main__":
    unittest.main()
