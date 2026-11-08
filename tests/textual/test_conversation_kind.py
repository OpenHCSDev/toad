"""Textual-facing: stable conversation identities resolve current names through Core references."""

from agent_comms.core_access import LocalCoreAccess
from agent_comms.projects.checkouts import Checkout
from agent_comms.launch_root import LaunchRoot
from dataclasses import FrozenInstanceError
from functools import partial

import pytest
from agent_comms.messaging.channel_targets import (
    ChannelTarget,
    IncarnationThreadTarget,
)
from agent_comms.comms import Comms
from agent_comms.active_route import resolve_comms_route
from support.roots import installed_wire
from support.agents import AppAgents
from agent_comms.nominal.field_codec import FieldCodec
from agent_comms.installer.backup import StoreBackup
from agent_comms.messaging.message_page import PageBounds
from agent_comms.registry.threads import NativeThread

from toad.constants import ALL_COMMS_TARGET
from toad.conversation_kind import ChannelConversation, ConversationKind, IrcConversation
from toad.message_rows import IrcMessageStyle
from toad.navigation_target import ChannelTarget as ChannelRoute
from toad.navigation_target import DirectTarget, FeedTarget, HistoryTarget
from toad.session_tracker import CommsViewKey
from toad.status_thread import NoStatusThread
from toad.referenced_core import ReferencedCore
from toad.wire_history import WireSource


class CoreAt(ReferencedCore):
    """The local Core at a root, as a conversation resolves names against it."""

    def __init__(self, comms: Comms) -> None:
        self.core = LocalCoreAccess(comms)
        self.root = comms.root


@pytest.fixture
def copied_conversations(tmp_path):
    original = installed_wire(tmp_path / "original")
    original.registry.declare(
        NativeThread("peer", frozenset({"team"}), Checkout(tmp_path))
    )
    viewer = original.messaging.user_identity(Checkout(tmp_path)).name
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
    resolved = route.prepare(CoreAt(comms), viewer)
    conversation = resolved.conversation
    references = comms.views.viewer_snapshot(Checkout(tmp_path)).references
    assert resolved.viewer == viewer
    assert conversation.label(references) == label
    assert HistoryTarget.for_conversation(conversation, references) == route
    page = conversation.page(
        WireSource(comms.root, conversation, comms.registry.require(viewer).worktree, viewer, IrcMessageStyle(),
                   access=AppAgents.unrun(tmp_path, LaunchRoot.from_path(comms.root)).app.coordination_access,
                      core=LocalCoreAccess(comms)),
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
    conversation = TeamConversation.resolve(CoreAt(comms), viewer, "#team").conversation
    references = comms.views.viewer_snapshot(Checkout(comms.root.parent)).references
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
    references = comms.views.viewer_snapshot(Checkout(comms.root.parent)).references
    with pytest.raises(KeyError):
        HistoryTarget.for_conversation(UnroutedConversation(ChannelTarget("#team")), references)


def test_kind_is_part_of_identity_and_each_conversation_has_one_view(copied_conversations):
    comms, viewer = copied_conversations
    conversation = ChannelConversation(ChannelTarget("#team"))
    with pytest.raises(FrozenInstanceError):
        conversation.target = ChannelTarget("#other")
    key = CommsViewKey(str(comms.root), conversation)
    assert key == CommsViewKey(str(comms.root), ChannelConversation(ChannelTarget("#team")))
    assert key != CommsViewKey(str(comms.root), IrcConversation(ChannelTarget("#team")))
    direct = DirectTarget("peer").prepare(CoreAt(comms), viewer).conversation
    assert key != CommsViewKey(str(comms.root), direct)
    assert len({key, CommsViewKey(str(comms.root), conversation)}) == 1
    # No session owns a conversation tab: one view per conversation, a DM as a channel.
    assert direct.view_identity(CommsViewKey(str(comms.root), direct)) == direct.view_identity(
        CommsViewKey(str(comms.root), DirectTarget("peer").prepare(CoreAt(comms), viewer).conversation)
    )


def test_dm_rename_retains_key_and_history_scope_but_resolves_current_name(copied_conversations):
    comms, viewer = copied_conversations
    direct = DirectTarget("peer").prepare(CoreAt(comms), viewer).conversation
    key = CommsViewKey(str(comms.root), direct)
    scope = direct.input_scope
    comms.registry.rename("peer", "renamed")
    reopened = DirectTarget("renamed").prepare(CoreAt(comms), viewer).conversation
    references = comms.views.viewer_snapshot(Checkout(comms.root.parent)).references
    assert direct == reopened
    assert key == CommsViewKey(str(comms.root), reopened)
    assert direct.input_scope == reopened.input_scope == scope
    assert direct.label(references) == "@renamed"
    assert direct.send_target().selected_name(comms.registry.snapshot()) == "renamed"
    assert HistoryTarget.for_conversation(direct, references) == DirectTarget("renamed")


def test_recreated_name_cannot_resolve_the_retired_dm(copied_conversations):
    comms, viewer = copied_conversations
    direct = DirectTarget("peer").prepare(CoreAt(comms), viewer).conversation
    comms.registry.unregister("peer")
    comms.threads.delete("peer")
    comms.registry.declare(NativeThread("peer", frozenset(), Checkout(comms.root.parent)))
    recreated = DirectTarget("peer").prepare(CoreAt(comms), viewer).conversation
    references = comms.views.viewer_snapshot(Checkout(comms.root.parent)).references
    assert recreated != direct
    assert CommsViewKey(str(comms.root), recreated) != CommsViewKey(str(comms.root), direct)
    assert recreated.label(references) == "@peer"
    # The retired DM answers for its own birth: never the successor that reused the name.
    assert direct.label(references) == "@peer (gone)"
    assert direct.destination(references) == IncarnationThreadTarget(direct.peer)
    assert recreated.destination(references) != direct.destination(references)


def test_history_picker_and_channel_status_use_the_same_declared_value(copied_conversations):
    from toad.screens.historical_sessions import HistoricalSessions

    comms, viewer = copied_conversations
    references = comms.views.viewer_snapshot(Checkout(comms.root.parent)).references
    create_view = partial(HistoricalSessions, comms, ())
    channel = ChannelConversation(ChannelTarget("#team"))
    direct = DirectTarget("peer").prepare(CoreAt(comms), viewer).conversation
    assert channel.historical_sessions(create_view, references).initial_name is None
    assert direct.historical_sessions(create_view, references).initial_name == "peer"
    assert isinstance(channel.status_thread(comms.root, object()), NoStatusThread)
