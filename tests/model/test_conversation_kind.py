"""Each kind of conversation reads its own history from Core, including a newly declared kind."""

from dataclasses import FrozenInstanceError, fields

import pytest

from agent_comms.comms import wire
from agent_comms.field_codec import FieldCodec
from agent_comms.message_page import PageBounds
from toad.conversation_kind import ChannelConversation, ConversationKind, DmConversation, IrcConversation
from toad.session_tracker import CommsViewKey
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


def test_conversation_value_is_frozen_and_its_kind_is_part_of_tab_identity():
    conversation = ChannelConversation("#team")
    assert [field.name for field in fields(conversation)] == ["target"]
    with pytest.raises(FrozenInstanceError):
        conversation.target = "#other"
    key = CommsViewKey("/wire", "owner", conversation)
    assert key == CommsViewKey("/wire", "owner", ChannelConversation("#team"))
    assert key != CommsViewKey("/wire", "owner", IrcConversation("#team"))
    assert key != CommsViewKey("/wire", "owner", DmConversation("#team"))
    assert len({key, CommsViewKey("/wire", "owner", conversation)}) == 1
    assert conversation.view_identity(key) == conversation.view_identity(
        CommsViewKey("/wire", "another-owner", conversation))
    direct = DmConversation("peer")
    assert direct.view_identity(CommsViewKey("/wire", "owner", direct)) != direct.view_identity(
        CommsViewKey("/wire", "another-owner", direct))


def test_conversation_resolves_a_renamed_peer_before_presentation(tmp_path):
    comms = wire(tmp_path / "wire")
    comms.registry.declare(comms.registry.new_thread("peer", frozenset(), str(tmp_path)))
    viewer = comms.messaging.user_identity(str(tmp_path)).name
    comms.registry.rename("peer", "renamed")
    conversation = DmConversation("peer")
    assert conversation.resolve(comms, viewer) == (viewer, DmConversation("renamed"))
    assert conversation.target == "peer"
