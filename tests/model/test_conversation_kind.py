"""Each kind of conversation reads its own history from Core, including a newly declared kind."""

from agent_comms.comms import wire
from agent_comms.field_codec import FieldCodec
from agent_comms.threads import Thread
from toad.conversation_kind import ChannelConversation, ConversationKind


def test_declared_kinds_read_history_and_a_new_kind_joins_the_family(tmp_path):
    class TeamConversation(ChannelConversation):
        pass

    comms = wire(tmp_path / "wire")
    comms.registry.declare(Thread("peer", frozenset({"team"}), str(tmp_path)))
    viewer = comms.messaging.user_identity(str(tmp_path)).name
    comms.messaging.send("peer", "#team", "channel body")
    comms.messaging.send("peer", viewer, "direct body")
    for kind in ConversationKind.members_with(ConversationKind):
        assert FieldCodec.decode(type[ConversationKind], FieldCodec.encode(kind)) is kind
        target = "peer" if kind.declared_name == "dm" else "#team"
        assert kind.resolve(comms, viewer, target) == (viewer, target)
        page = kind.page(comms, target, worktree=str(tmp_path), limit=8)
        assert page.messages
        assert kind.display_identity(page) is not None
    assert ConversationKind.decode("team").label("#team") == "#team"
