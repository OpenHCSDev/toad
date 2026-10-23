"""Textual-facing: the presentation window; a wire source pages one conversation and notices when Core replaces its reading."""

from agent_comms.channel_targets import ChannelTarget
from support.roots import installed_wire
from agent_comms.historical_views import ConversationObservation
from agent_comms.page_traversal import LiveCursor

from toad.conversation_kind import ChannelConversation, DmConversation
from toad.transcript_preparation import PageRequest, Unchanged
from toad.widgets.presentation_window import OLDER_END, NEWER_END
from toad.message_rows import IrcMessageStyle
from toad.wire_history import AfterSequence, MessageFragment, WireSource


def channel_source(comms, target, project):
    viewer = comms.messaging.user_identity(str(project)).name
    return WireSource(comms, ChannelConversation(ChannelTarget(target)), project, viewer, IrcMessageStyle())


def observed(source):
    """What a view that just drew the newest page remembers of it."""
    first = source.observe(ConversationObservation())
    assert first.replaced
    newest = source.read(PageRequest(OLDER_END, first.through), first.through)
    return first, newest


def test_a_turn_claim_on_the_peer_keeps_the_direct_message_page_identity(tmp_path):
    import os

    from agent_comms.child_process import ProcessIdentity

    comms = installed_wire(tmp_path / "wire")
    comms.registry.declare(comms.registry.new_thread("peer", frozenset(), str(tmp_path), process_identity=ProcessIdentity.capture(os.getpid())))
    viewer = comms.messaging.user_identity(str(tmp_path)).name
    comms.messaging.send("peer", viewer, "shown across turn claim")
    before = comms.views.dm_display_page("peer", worktree=str(tmp_path))
    comms.registry.lease_local_turn("peer", "new-turn")
    after = comms.views.dm_display_page("peer", worktree=str(tmp_path))
    assert DmConversation.history_view.same_display(after, before)


def test_pages_lie_between_cuts_and_a_read_never_passes_its_bound(tmp_path):
    comms = installed_wire(tmp_path / "wire")
    comms.registry.declare(comms.registry.new_thread("sender", frozenset({"one", "two"}), str(tmp_path)))
    for index in range(60):
        comms.messaging.send("sender", "#one", f"Message {index}")
        comms.messaging.send("sender", "#two", f"Elsewhere {index}")
    source = channel_source(comms, "#one", tmp_path)
    first, newest = observed(source)

    def bodies(prepared):
        return [fragment.message.body for fragment in prepared.fragments]

    assert bodies(newest) == [f"Message {index}" for index in range(52, 60)]
    assert newest.page.after == first.through and not newest.page.has_newer and newest.page.has_older
    assert all(isinstance(fragment, MessageFragment) and not fragment.outgoing_sources
               for fragment in newest.fragments)
    earlier = source.read(PageRequest(OLDER_END, newest.page.before), first.through)
    assert bodies(earlier) == [f"Message {index}" for index in range(12, 52)]
    assert earlier.page.has_newer and earlier.page.has_older
    oldest = source.read(PageRequest(OLDER_END, earlier.page.before), first.through)
    assert bodies(oldest) == [f"Message {index}" for index in range(12)] and not oldest.page.has_older
    assert bodies(source.read(PageRequest(NEWER_END, oldest.page.after), first.through))[:3] == [
        "Message 12", "Message 13", "Message 14"]

    comms.messaging.send("sender", "#two", "Elsewhere again")
    grown = source.observe(first.revision)
    assert grown.through.cursor.sequence > first.through.cursor.sequence and not grown.replaced
    nothing = source.read(PageRequest(NEWER_END, first.through), grown.through)
    assert not nothing.fragments and nothing.page.after == grown.through
    comms.messaging.send("sender", "#one", "arrived later")
    comms.messaging.send("sender", "#one", "arrived after the bound")
    later = AfterSequence(LiveCursor(grown.through.cursor.sequence + 1))
    bounded = source.read(PageRequest(NEWER_END, grown.through), later)
    assert bodies(bounded) == ["arrived later"] and bounded.page.after == later and not bounded.page.has_newer
    current = source.observe(grown.revision)
    assert isinstance(source.observe(current.revision), Unchanged)


def test_any_mode_expansion_replaces_the_reading_without_new_bus_rows(tmp_path):
    comms = installed_wire(tmp_path / "wire")
    comms.registry.declare(comms.registry.new_thread("alice", frozenset({"team"}), str(tmp_path)))
    comms.registry.declare(comms.registry.new_thread("carol", frozenset({"team"}), str(tmp_path)))
    comms.registry.declare(comms.registry.new_thread("dave", frozenset(), str(tmp_path)))
    comms.messaging.send("carol", "dave", "older DM")
    comms.messaging.send("alice", "#team", "channel message")
    source = channel_source(comms, "#team", tmp_path)
    first, newest = observed(source)
    assert [fragment.message.body for fragment in newest.fragments] == ["channel message"]
    comms.channels.set_channel_any_mode("#team", True)
    assert comms.bus.bus.revision() == first.through.cursor.sequence
    expanded = source.observe(first.revision)
    assert expanded.replaced and expanded.through == first.through
    again = source.read(PageRequest(OLDER_END, expanded.through), expanded.through)
    assert [fragment.message.body for fragment in again.fragments] == ["older DM", "channel message"]


def test_attaching_or_detaching_history_replaces_the_reading_without_new_live_messages(tmp_path):
    old = installed_wire(tmp_path / "old")
    comms = installed_wire(tmp_path / "live")
    for bus in (old, comms):
        bus.registry.declare(bus.registry.new_thread("alice", frozenset({"team"}), str(tmp_path)))
        bus.messaging.send("alice", "#team", bus.root.name)
    source = channel_source(comms, "#team", tmp_path)
    first, _newest = observed(source)
    comms.views.attach_history(old.root)
    attached = source.observe(first.revision)
    assert attached.replaced and attached.through == first.through
    page = source.read(PageRequest(OLDER_END, attached.through), attached.through)
    assert [message.body for message in page.page.events] == ["old", "live"]
    comms.bus.history.path.unlink()
    detached = source.observe(attached.revision)
    assert detached.replaced
    remaining = source.read(PageRequest(OLDER_END, detached.through), detached.through)
    assert [message.body for message in remaining.page.events] == ["live"]
    assert not remaining.page.has_older
