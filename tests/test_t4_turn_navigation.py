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
                view = app.screen.conversation
                await view.contents.remove_children()
                note, response, extra = Note("atomic"), AgentResponse("first\n\nsecond"), ExtraBlock("new declaration")
                await view.contents.mount(note, response, extra)
                await pilot.pause()
                view.move_cursor(UpCursor())
                self.assertIs(view.cursor_block_child, extra)
                view.move_cursor(UpCursor())
                self.assertIs(view.cursor_block, response)
                self.assertIsNotNone(view.cursor_block_child)
                entered = view.cursor_block_child
                visited = [entered]
                for _ in range(len(response.displayed_children)):
                    view.move_cursor(UpCursor())
                    if view.cursor_block is not response:
                        break
                    visited.append(view.cursor_block_child)
                self.assertEqual(visited, list(reversed(response.displayed_children)))
                self.assertIs(view.cursor_block_child, note)
                self.assertTrue(view.navigation.select(entered))
                self.assertIs(view.cursor_block_child, entered)
                view.move_cursor(DownCursor())
                self.assertIs(view.cursor_block_child, extra)
                view.move_cursor(DownCursor())
                self.assertIsNone(view.cursor_block_child)
                view.move_cursor(DownCursor())
                self.assertIsNone(view.cursor_block_child)


if __name__ == '__main__':
    unittest.main(verbosity=2)
