"""Textual-facing: stable conversation identities resolve current names through Core references."""

from dataclasses import FrozenInstanceError
from functools import partial

import pytest
from agent_comms.channel_targets import ChannelTarget
from agent_comms.comms import Comms
from agent_comms.active_route import resolve_comms_route
from support.roots import installed_wire
from agent_comms.field_codec import FieldCodec
from agent_comms.installer.backup import StoreBackup
from agent_comms.message_page import PageBounds

from toad.constants import ALL_COMMS_TARGET
from toad.conversation_kind import ChannelConversation, ConversationKind, IrcConversation
from toad.message_rows import IrcMessageStyle
from toad.navigation_target import ChannelTarget as ChannelRoute
from toad.navigation_target import DirectTarget, FeedTarget, HistoryTarget
from toad.session_tracker import CommsViewKey
from toad.status_thread import NoStatusThread
from toad.wire_history import WireSource


@pytest.fixture
def copied_conversations(tmp_path):
    original = installed_wire(tmp_path / "original")
    original.registry.declare(
        original.registry.new_thread("peer", frozenset({"team"}), str(tmp_path))
    )
    viewer = original.messaging.user_identity(str(tmp_path)).name
    original.messaging.send("peer", "#team", "channel body")
    original.messaging.send("peer", viewer, "direct body")
    StoreBackup.copy_tree(original.root, tmp_path / "copied")
    return Comms(resolve_comms_route(tmp_path / "copied")), viewer


@pytest.mark.parametrize("route,label,body", [
    (DirectTarget("peer"), "@peer", "direct body"),
    (ChannelRoute("#team"), "#team", "channel body"),
    (FeedTarget(), f"{ALL_COMMS_TARGET} · all comms", "direct body"),
])
def test_conversation_family_resolves_copied_pages_and_current_labels(
    copied_conversations, tmp_path, route, label, body,
):
    comms, viewer = copied_conversations
    resolved = route.prepare(comms, viewer)
    conversation = resolved.conversation
    references = comms.views.viewer_snapshot(str(tmp_path)).references
    assert resolved.viewer == viewer
    assert conversation.label(references) == label
    assert HistoryTarget.for_conversation(conversation, references) == route
    page = conversation.page(
        WireSource(comms, conversation, tmp_path, viewer, IrcMessageStyle()),
        PageBounds(limit=8),
    )
    assert body in [message.body for message in page.messages]
    assert FieldCodec.decode(type[ConversationKind], FieldCodec.encode(type(conversation))) is type(conversation)
    with pytest.raises(FrozenInstanceError):
        resolved.viewer = "another-viewer"


def test_new_channel_kind_inherits_destination_resolution(copied_conversations):
    class TeamConversation(ChannelConversation):
        pass

    comms, viewer = copied_conversations
    conversation = TeamConversation.resolve(comms, viewer, "#team").conversation
    references = comms.views.viewer_snapshot(str(comms.root.parent)).references
    assert ConversationKind.member_named("team") is TeamConversation
    assert conversation == TeamConversation(ChannelTarget("#team"))
    assert conversation.label(references) == "#team"


def test_routes_reject_duplicate_declarations_and_unregistered_kinds(copied_conversations):
    with pytest.raises(TypeError):
        class DuplicateDirectTarget(DirectTarget):
            pass

    class UnroutedConversation(ChannelConversation):
        pass

    comms, _ = copied_conversations
    references = comms.views.viewer_snapshot(str(comms.root.parent)).references
    with pytest.raises(KeyError):
        HistoryTarget.for_conversation(UnroutedConversation(ChannelTarget("#team")), references)


def test_kind_and_owner_are_part_of_identity_but_channel_address_is_shared(copied_conversations):
    comms, viewer = copied_conversations
    conversation = ChannelConversation(ChannelTarget("#team"))
    with pytest.raises(FrozenInstanceError):
        conversation.target = ChannelTarget("#other")
    key = CommsViewKey(str(comms.root), "owner", conversation)
    assert key == CommsViewKey(str(comms.root), "owner", ChannelConversation(ChannelTarget("#team")))
    assert key != CommsViewKey(str(comms.root), "owner", IrcConversation(ChannelTarget("#team")))
    direct = DirectTarget("peer").prepare(comms, viewer).conversation
    assert key != CommsViewKey(str(comms.root), "owner", direct)
    assert len({key, CommsViewKey(str(comms.root), "owner", conversation)}) == 1
    assert conversation.view_identity(key) == conversation.view_identity(
        CommsViewKey(str(comms.root), "another-owner", conversation)
    )
    assert direct.view_identity(CommsViewKey(str(comms.root), "owner", direct)) != direct.view_identity(
        CommsViewKey(str(comms.root), "another-owner", direct)
    )


def test_dm_rename_retains_key_and_history_scope_but_resolves_current_name(copied_conversations):
    comms, viewer = copied_conversations
    direct = DirectTarget("peer").prepare(comms, viewer).conversation
    key = CommsViewKey(str(comms.root), "owner", direct)
    scope = direct.input_scope
    comms.registry.rename("peer", "renamed")
    reopened = DirectTarget("renamed").prepare(comms, viewer).conversation
    references = comms.views.viewer_snapshot(str(comms.root.parent)).references
    assert direct == reopened
    assert key == CommsViewKey(str(comms.root), "owner", reopened)
    assert direct.input_scope == reopened.input_scope == scope
    assert direct.label(references) == "@renamed"
    assert direct.send_target().selected_name(references.registry) == "renamed"
    assert HistoryTarget.for_conversation(direct, references) == DirectTarget("renamed")


def test_recreated_name_cannot_resolve_the_retired_dm(copied_conversations):
    comms, viewer = copied_conversations
    direct = DirectTarget("peer").prepare(comms, viewer).conversation
    comms.registry.unregister("peer")
    comms.threads.delete("peer")
    comms.registry.declare(comms.registry.new_thread("peer", frozenset(), str(comms.root.parent)))
    recreated = DirectTarget("peer").prepare(comms, viewer).conversation
    references = comms.views.viewer_snapshot(str(comms.root.parent)).references
    assert recreated != direct
    assert CommsViewKey(str(comms.root), "owner", recreated) != CommsViewKey(str(comms.root), "owner", direct)
    assert recreated.label(references) == "@peer"
    with pytest.raises(KeyError):
        direct.destination(references)


def test_history_picker_and_channel_status_use_the_same_declared_value(copied_conversations):
    from toad.screens.historical_sessions import HistoricalSessions

    comms, viewer = copied_conversations
    references = comms.views.viewer_snapshot(str(comms.root.parent)).references
    create_view = partial(HistoricalSessions, comms, ())
    channel = ChannelConversation(ChannelTarget("#team"))
    direct = DirectTarget("peer").prepare(comms, viewer).conversation
    assert channel.historical_sessions(create_view, references).initial_name is None
    assert direct.historical_sessions(create_view, references).initial_name == "peer"
    assert isinstance(channel.status_thread(comms.root, object()), NoStatusThread)
