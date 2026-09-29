"""Declared conversation reads use actual Comms history, including a new member."""

from pathlib import Path
import tempfile
import unittest
from agent_comms.comms import wire
from agent_comms.field_codec import FieldCodec
from agent_comms.threads import Thread
from toad.conversation_kind import ConversationKind, ChannelConversation


class ConversationFamilyTests(unittest.TestCase):
    def test_declared_reads_and_new_member(self):
        class TeamConversation(ChannelConversation):
            pass

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            comms = wire(project / "wire")
            comms.registry.declare(Thread("peer", frozenset({"team"}), str(project)))
            viewer = comms.messaging.user_identity(str(project)).name
            comms.messaging.send("peer", "#team", "channel body")
            comms.messaging.send("peer", viewer, "direct body")
            for kind in ConversationKind.members_with(ConversationKind):
                self.assertIs(
                    FieldCodec.decode(type[ConversationKind], FieldCodec.encode(kind)),
                    kind,
                )
                target = "peer" if kind.declared_name == "dm" else "#team"
                canonical_viewer, canonical_target = kind.resolve(comms, viewer, target)
                self.assertEqual(canonical_viewer, viewer)
                self.assertEqual(canonical_target, target)
                page = kind.page(comms, target, worktree=str(project), limit=8)
                self.assertTrue(page.messages)
                self.assertIsNotNone(kind.display_identity(page))
            self.assertEqual(ConversationKind.decode("team").label("#team"), "#team")


if __name__ == "__main__":
    unittest.main(verbosity=2)
