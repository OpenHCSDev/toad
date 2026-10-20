"""Each kind of conversation reads its own history from Core, including a newly declared kind."""

from agent_comms.comms import wire
from agent_comms.field_codec import FieldCodec
from agent_comms.message_page import PageBounds
from toad.conversation_kind import ChannelConversation, ConversationKind
from toad.message_rows import IrcMessageStyle
from toad.wire_history import WireSource


def test_declared_kinds_read_history_and_a_new_kind_joins_the_family(tmp_path):
    class TeamConversation(ChannelConversation):
        pass

    comms = wire(tmp_path / "wire")
    comms.registry.declare(comms.registry.new_thread("peer", frozenset({"team"}), str(tmp_path)))
    viewer = comms.messaging.user_identity(str(tmp_path)).name
    comms.messaging.send("peer", "#team", "channel body")
    comms.messaging.send("peer", viewer, "direct body")
    for kind in ConversationKind.members_with(ConversationKind):
        assert FieldCodec.decode(type[ConversationKind], FieldCodec.encode(kind)) is kind
        target = "peer" if kind.declared_name == "dm" else "#team"
        conversation = kind(target)
        assert conversation.resolve(comms, viewer) == (viewer, conversation)
        assert conversation.resolve(comms, viewer)[1] is conversation
        page = conversation.page(WireSource(comms, conversation, tmp_path, viewer, IrcMessageStyle()), PageBounds(limit=8))
        assert page.messages
    assert ConversationKind.member_named("team")("#team").label() == "#team"
