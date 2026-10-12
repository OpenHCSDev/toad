"""A wire source pages one conversation from Core and notices when the viewer's reading of it was replaced."""

from agent_comms.comms import wire
from agent_comms.threads import Thread

from toad.conversation_kind import ChannelConversation, DmConversation
from toad.transcript_preparation import PageRequest
from toad.message_rows import IrcMessageStyle
from toad.wire_history import AfterSequence, MessageFragment, WireSource


def channel_source(comms, target, project):
    viewer = comms.messaging.user_identity(str(project)).name
    return WireSource(comms, ChannelConversation, target, project, viewer, IrcMessageStyle())


def observed(source):
    """What a view that just drew the newest page remembers of it."""
    first = source.observe(None, AfterSequence(0), None)
    assert first.replaced
    newest = source.read(PageRequest(before=first.through), first.through)
    return first, newest, source.kind.display_identity(newest.page.source)


def test_a_turn_claim_on_the_peer_keeps_the_direct_message_page_identity(tmp_path):
    import os

    from agent_comms.child_process import ProcessIdentity

    comms = wire(tmp_path / "wire")
    comms.registry.declare(Thread("peer", frozenset(), str(tmp_path), process_identity=ProcessIdentity.capture(os.getpid())))
    viewer = comms.messaging.user_identity(str(tmp_path)).name
    comms.messaging.send("peer", viewer, "shown across turn claim")
    identity = DmConversation.display_identity(comms.views.dm_display_page("peer", worktree=str(tmp_path)))
    comms.registry.lease_local_turn("peer", "new-turn")
    assert identity == DmConversation.display_identity(comms.views.dm_display_page("peer", worktree=str(tmp_path)))


def test_pages_lie_between_cuts_and_a_read_never_passes_its_bound(tmp_path):
    comms = wire(tmp_path / "wire")
    comms.registry.declare(Thread("sender", frozenset({"one", "two"}), str(tmp_path)))
    for index in range(60):
        comms.messaging.send("sender", "#one", f"Message {index}")
        comms.messaging.send("sender", "#two", f"Elsewhere {index}")
    source = channel_source(comms, "#one", tmp_path)
    first, newest, _identity = observed(source)

    def bodies(prepared):
        return [fragment.message.body for fragment in prepared.fragments]

    # The newest page is short; it ends at the bound, with nothing newer.
    assert bodies(newest) == [f"Message {index}" for index in range(52, 60)]
    assert newest.page.after == first.through and not newest.page.has_newer and newest.page.has_older
    assert all(isinstance(fragment, MessageFragment) and not fragment.outgoing
               for fragment in newest.fragments)
    # Earlier pages are whole transport pages, each beginning where the next one ended.
    earlier = source.read(PageRequest(before=newest.page.before), first.through)
    assert bodies(earlier) == [f"Message {index}" for index in range(12, 52)]
    assert earlier.page.has_newer and earlier.page.has_older
    oldest = source.read(PageRequest(before=earlier.page.before), first.through)
    assert bodies(oldest) == [f"Message {index}" for index in range(12)] and not oldest.page.has_older
    # Paging forward again from a cut reaches the same messages.
    assert bodies(source.read(PageRequest(after=oldest.page.after), first.through))[:3] == [
        "Message 12", "Message 13", "Message 14"]

    comms.messaging.send("sender", "#two", "Elsewhere again")
    grown = source.observe(first.revision, first.through, None)
    assert grown.through.cursor > first.through.cursor and not grown.replaced
    # Nothing of this conversation arrived: the page is empty and ends at the new bound.
    nothing = source.read(PageRequest(after=first.through), grown.through)
    assert not nothing.fragments and nothing.page.after == grown.through
    comms.messaging.send("sender", "#one", "arrived later")
    comms.messaging.send("sender", "#one", "arrived after the bound")
    later = AfterSequence(grown.through.cursor + 1)
    bounded = source.read(PageRequest(after=grown.through), later)
    assert bodies(bounded) == ["arrived later"] and bounded.page.after == later and not bounded.page.has_newer
    # Unchanged stores are not read again.
    current = source.observe(grown.revision, grown.through, None)
    assert source.observe(current.revision, current.through, None) is None


def test_any_mode_expansion_replaces_the_reading_without_new_bus_rows(tmp_path):
    comms = wire(tmp_path / "wire")
    comms.registry.declare(Thread("alice", frozenset({"team"}), str(tmp_path)))
    comms.registry.declare(Thread("carol", frozenset({"team"}), str(tmp_path)))
    comms.registry.declare(Thread("dave", frozenset(), str(tmp_path)))
    comms.messaging.send("carol", "dave", "older DM")
    comms.messaging.send("alice", "#team", "channel message")
    source = channel_source(comms, "#team", tmp_path)
    first, newest, identity = observed(source)
    assert [fragment.message.body for fragment in newest.fragments] == ["channel message"]
    comms.channels.set_channel_any_mode("#team", True)
    assert comms.bus.log.latest_sequence() == first.through.cursor
    expanded = source.observe(first.revision, first.through, identity)
    assert expanded.replaced and expanded.through == first.through
    again = source.read(PageRequest(before=expanded.through), expanded.through)
    assert [fragment.message.body for fragment in again.fragments] == ["older DM", "channel message"]


def test_attaching_or_detaching_history_replaces_the_reading_without_new_live_messages(tmp_path):
    old = wire(tmp_path / "old")
    comms = wire(tmp_path / "live")
    for bus in (old, comms):
        bus.registry.declare(Thread("alice", frozenset({"team"}), str(tmp_path)))
        bus.messaging.send("alice", "#team", bus.root.name)
    source = channel_source(comms, "#team", tmp_path)
    first, _newest, identity = observed(source)
    comms.views.attach_history(old.root)
    attached = source.observe(first.revision, first.through, identity)
    assert attached.replaced and attached.through == first.through
    page = source.read(PageRequest(before=attached.through), attached.through)
    assert page.page.has_older
    identity = source.kind.display_identity(page.page.source)
    # Detaching changes the same reading without a new live sequence.
    comms.bus.history.path.unlink()
    detached = source.observe(attached.revision, attached.through, identity)
    assert detached.replaced
    assert not source.read(PageRequest(before=detached.through), detached.through).page.has_older
