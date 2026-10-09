"""Turn permissions and actual mounted mixed-block navigation."""
import asyncio
import os
from pathlib import Path
import tempfile
import unittest

from toad.conversation_turn import TurnOwner, NoTurn, ClientTurn, AgentTurn
from toad.block_navigation import ConversationBlock, UpCursor, DownCursor
from toad.widgets.agent_response import AgentResponse
from toad.widgets.note import Note
from textual.document._markdown import MarkdownSourceBlock
from textual.widgets._markdown import MarkdownBlock
from textual.widgets import Static
from runtime_fixture import ToadApp


class T4Tests(unittest.IsolatedAsyncioTestCase):
    def test_turn_family_permissions_and_new_case(self):
        class ReviewingTurn(TurnOwner):
            busy = False
            session_state = "idle"
            can_compact = False
        for owner in (NoTurn(), ClientTurn(), AgentTurn("actual"), ReviewingTurn()):
            self.assertEqual(owner.accepts_prompt, not owner.busy)
        self.assertFalse(AgentTurn("actual").can_compact)
        self.assertTrue(ClientTurn().can_compact)
        self.assertFalse(ReviewingTurn().can_compact)
        self.assertTrue(AgentTurn("actual").matches_settlement("actual"))
        self.assertFalse(AgentTurn("actual").matches_settlement("obsolete"))

    async def test_actual_mixed_blocks_and_new_block(self):
        class ExtraBlock(ConversationBlock, Static):
            pass
        with tempfile.TemporaryDirectory(prefix="t4-blocks-") as directory:
            root = Path(directory)
            os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'), XDG_CONFIG_HOME=str(root/'config'),
                              XDG_DATA_HOME=str(root/'data'), XDG_STATE_HOME=str(root/'state'))
            app = ToadApp(project_dir=str(root))
            async with app.run_test(size=(120,40)) as pilot:
                await pilot.pause()
                view = app.selected_session.conversation
                await view.contents.remove_children()
                app.stylesheet.add_source("PreparedH2 { display: none; }", read_from=(__file__, "hidden-heading"))
                app.refresh_css(animate=False)
                source = "# Heading\n\nA paragraph.\n\n## Hidden\n\n```python\nprint('code')\n```\n\n- outer\n  - inner\n"
                note, response, extra = Note("atomic"), AgentResponse(source), ExtraBlock("new declaration")
                await view.contents.mount(note, response, extra)
                await pilot.pause()
                await response.restore_body()
                measurement = response._body_measurement
                paint = measurement.document_paint
                document = response.document
                demand_width = measurement.width + response.styles.gutter.width
                print({"initial_response": {
                    "measurement": type(measurement).__name__, "width": measurement.width,
                    "demand_width": demand_width, "rows": measurement.rows,
                    "dormant": measurement.dormant, "ready": measurement.ready(response),
                    "attached": response.is_attached, "closing": response._closing,
                    "source_characters": len(response.source), "loading": response.loading,
                    "requested_characters": len(response._pending_source),
                    "initial_source_pending": response._initial_markdown is not None,
                    "source_generation": response._content_generation,
                    "fragments": len(response.fragments), "fragment_views": len(response.fragment_views),
                    "geometry": repr(response.screen._compositor.visible_widgets.get(response)),
                    "document": document is not None, "paint": paint is not None,
                    "same_source": None if paint is None or document is None else paint.document.same_source(document),
                    "paint_current": None if paint is None else paint.is_current(response, demand_width),
                }}, flush=True)
                part, = response.fragment_views
                self.assertEqual(response._pending_source, source)
                self.assertEqual(response.source, source)
                await part.restore_body()
                await pilot.pause()
                self.assertFalse(part.query(MarkdownBlock))
                hidden, = (root for root in part._body_measurement.document_resource.document_paint.roots
                           if root.source_text() == "## Hidden\n")
                self.assertIsNone(hidden.placement)
                view.move_cursor(UpCursor())
                self.assertIs(view.cursor_block_child, extra)
                view.move_cursor(UpCursor())
                self.assertIs(view.cursor_block, response)
                # Entry may precede the focus-dependent document publication.
                # The original cursor holds that target through frame admission.
                self.assertIs(view.navigation.cursor, part.block_cursor)
                await pilot.pause()
                self.assertIsNotNone(view.cursor_block_child)
                entered = view.cursor_block_child
                self.assertIsInstance(entered, MarkdownSourceBlock)
                expected = ["- outer\n  - inner\n", "```python\nprint('code')\n```\n",
                            "A paragraph.\n", "# Heading\n", None]
                for raw in expected:
                    await pilot.pause()
                    await part.restore_body()
                    cursor = view.navigation.cursor
                    self.assertEqual(cursor.get_prompt_text(), raw)
                    if raw is not None:
                        view.action_copy_to_clipboard()
                        self.assertEqual(app.clipboard, "print('code')" if raw.startswith("```") else raw)
                        self.assertFalse(cursor.allow_maximize)
                        size, render = cursor.export_render()
                        from rich.console import Console
                        console = Console(width=size.width, height=size.height, record=True)
                        with console.capture():
                            console.print(render)
                        self.assertIn("<svg", console.export_svg())
                    if raw is not None and raw.startswith("```"):
                        await view.action_select_block()
                        from toad.widgets.menu import Menu
                        menu = view.query_one(Menu)
                        self.assertTrue(cursor.accepts(menu._owner))
                        self.assertNotIn("maximize_block", [item.action for item in menu._options])
                        await menu.remove()
                        view.prompt.append("draft ")
                        view.prompt.prompt_text_area.history.checkpoint()
                        view.action_copy_to_prompt()
                        self.assertEqual(view.prompt.text, "draft " + raw)
                        view.prompt.prompt_text_area.undo()
                        self.assertEqual(view.prompt.text, "draft ")
                        self.assertIsNone(view.navigation.cursor)
                        # Copy-to-prompt intentionally leaves content navigation.
                        # Re-enter through the original keys, not a source update.
                        for _ in range(3):
                            view.move_cursor(UpCursor())
                            await pilot.pause()
                        self.assertEqual(view.navigation.cursor.get_prompt_text(), raw)
                    view.move_cursor(UpCursor())
                self.assertIs(view.cursor_block_child, note)
                view.move_cursor(UpCursor())
                self.assertIs(view.cursor_block_child, note)
                # A sibling insertion must not reinterpret the selected block.
                before = ExtraBlock("inserted before the reader")
                await view.contents.mount(before, before=note)
                self.assertIs(view.cursor_block_child, note)
                await before.remove()
                for _ in expected:
                    view.move_cursor(DownCursor())
                self.assertTrue(view.navigation.cursor.accepts(entered))
                # Width changes prepare through the original viewport worker.
                document = part.document
                await pilot.resize_terminal(100, 40)
                await part.restore_body()
                await pilot.pause()
                self.assertTrue(document.same_source(part.document))
                self.assertTrue(view.navigation.cursor.accepts(entered))
                self.assertEqual(view.navigation.cursor.get_prompt_text(), expected[0])
                self.assertFalse(part.query(MarkdownBlock))
                view.move_cursor(DownCursor())
                self.assertIs(view.cursor_block_child, extra)
                view.move_cursor(DownCursor())
                self.assertIsNone(view.cursor_block_child)
                view.move_cursor(DownCursor())
                self.assertIsNone(view.cursor_block_child)
                # Native pointer ownership selects actual controls after the
                # original interactive-body acquisition, not paint descendants.
                view.move_cursor(UpCursor())
                view.move_cursor(UpCursor())
                self.assertTrue(view.navigation.cursor.accepts(entered))
                await response.materialize_interactive_body()
                native = part.displayed_children[-1]
                self.assertTrue(view.navigation.select(native))
                self.assertIsInstance(view.cursor_block_child, MarkdownSourceBlock)
                self.assertTrue(view.navigation.cursor.accepts(entered))
                self.assertEqual(view.navigation.cursor.get_prompt_text(), expected[0])
                # Reacquiring equal text is still a different source lifetime.
                await part.update(part.source)
                await pilot.pause()
                self.assertFalse(document.same_source(part.document))
                self.assertIsNone(view.cursor_block_child)
                self.assertFalse(part._document_block_cursor.accepts(entered))
                print({"worker_roots_navigation_copy_menu_svg": "passed",
                       "draft_undo_native_controls_source_currentness": "passed"})


if __name__ == '__main__':
    unittest.main(verbosity=2)
