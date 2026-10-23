"""Textual-facing: the historical sessions screen and observed thread activity widget; conversation values retain Core destination identities through copied history."""

from dataclasses import FrozenInstanceError, fields
from functools import partial

import pytest

from agent_comms.channel_targets import ChannelTarget, ThreadTarget
from agent_comms.comms import Comms
from agent_comms.field_codec import FieldCodec
from agent_comms.installer.backup import StoreBackup
from agent_comms.message_page import PageBounds
from support.roots import installed_wire
from toad.constants import ALL_COMMS_TARGET
from toad.conversation_kind import (
    ChannelConversation, ConversationKind, DmConversation, IrcConversation, ResolvedConversation,
)
from toad.session_tracker import CommsViewKey
from toad.message_rows import IrcMessageStyle
from toad.wire_history import WireSource


@pytest.fixture
def copied_conversations(tmp_path):
    original = installed_wire(tmp_path / "original")
    original.registry.declare(original.registry.new_thread("peer", frozenset({"team"}), str(tmp_path)))
    viewer = original.messaging.user_identity(str(tmp_path)).name
    original.messaging.send("peer", "#team", "channel body")
    original.messaging.send("peer", viewer, "direct body")
    StoreBackup.copy_tree(original.root, tmp_path / "copied")
    return Comms(tmp_path / "copied"), viewer


@pytest.mark.parametrize("conversation,label,body", [
    (DmConversation(ThreadTarget("peer")), "@peer", "direct body"),
    (ChannelConversation(ChannelTarget("#team")), "#team", "channel body"),
    (IrcConversation(ChannelTarget(ALL_COMMS_TARGET)), f"{ALL_COMMS_TARGET} · all comms", "direct body"),
])
def test_typed_conversation_resolves_pages_and_labels_on_a_copied_bus(
    copied_conversations, tmp_path, conversation, label, body,
):
    comms, viewer = copied_conversations
    resolved = conversation.resolve(comms, viewer)
    assert resolved == ResolvedConversation(viewer, conversation)
    assert resolved.conversation.label() == label
    assert resolved.conversation.target == conversation.target
    page = resolved.conversation.page(
        WireSource(comms, resolved.conversation, tmp_path, viewer, IrcMessageStyle()), PageBounds(limit=8),
    )
    assert body in [message.body for message in page.messages]
    assert FieldCodec.decode(type[ConversationKind], FieldCodec.encode(type(conversation))) is type(conversation)
    with pytest.raises(FrozenInstanceError):
        resolved.viewer = "another-viewer"


def test_new_channel_kind_inherits_its_typed_destination_and_resolution(copied_conversations):
    class TeamConversation(ChannelConversation):
        pass

    comms, viewer = copied_conversations
    conversation = TeamConversation(ChannelTarget("#team"))
    assert ConversationKind.member_named("team") is TeamConversation
    assert conversation.resolve(comms, viewer).conversation == conversation
    assert conversation.label() == "#team"


def test_conversation_value_is_frozen_and_its_kind_is_part_of_tab_identity():
    conversation = ChannelConversation(ChannelTarget("#team"))
    assert [field.name for field in fields(conversation)] == ["target"]
    with pytest.raises(FrozenInstanceError):
        conversation.target = ChannelTarget("#other")
    key = CommsViewKey("/wire", "owner", conversation)
    assert key == CommsViewKey("/wire", "owner", ChannelConversation(ChannelTarget("#team")))
    assert key != CommsViewKey("/wire", "owner", IrcConversation(ChannelTarget("#team")))
    assert key != CommsViewKey("/wire", "owner", DmConversation(ThreadTarget("peer")))
    assert len({key, CommsViewKey("/wire", "owner", conversation)}) == 1
    assert conversation.view_identity(key) == conversation.view_identity(
        CommsViewKey("/wire", "another-owner", conversation))
    direct = DmConversation(ThreadTarget("peer"))
    assert direct.view_identity(CommsViewKey("/wire", "owner", direct)) != direct.view_identity(
        CommsViewKey("/wire", "another-owner", direct))


def test_conversation_resolves_a_renamed_peer_before_presentation(tmp_path):
    comms = installed_wire(tmp_path / "wire")
    comms.registry.declare(comms.registry.new_thread("peer", frozenset(), str(tmp_path)))
    viewer = comms.messaging.user_identity(str(tmp_path)).name
    comms.registry.rename("peer", "renamed")
    conversation = DmConversation(ThreadTarget("peer"))
    assert conversation.resolve(comms, viewer) == ResolvedConversation(
        viewer, DmConversation(ThreadTarget("renamed")),
    )
    assert conversation.target == ThreadTarget("peer")


def test_conversation_selects_the_saved_history_identity_and_channel_status(tmp_path):
    from toad.screens.historical_sessions import HistoricalSessions
    from toad.widgets.observed_thread_activity import NoStatusThread

    comms = installed_wire(tmp_path / "wire")
    create_view = partial(HistoricalSessions, comms, ())
    channel = ChannelConversation(ChannelTarget("#team"))
    assert channel.historical_sessions(create_view).initial_name is None
    assert DmConversation(ThreadTarget("peer")).historical_sessions(create_view).initial_name == "peer"
    assert isinstance(channel.status_thread(comms.root, object()), NoStatusThread)
