"""A replay belongs to its requested tab, not whichever tab is still opening."""

from agent_comms.projects.checkouts import Checkout
from agent_comms.session_file import RegistrySessionLocation
from dataclasses import replace

from agent_comms.acp_extension import TranscriptSnapshotUpdate, encode_updates
from agent_comms.registry.threads import NativeThread
from toad.acp.agent_controller import SessionBinding

from support.agents import deliver
from support.coordination import carrying, coordination_fact
from support.journals import assistant_entry, write_journal


async def test_unbound_tab_refuses_another_threads_snapshot(workspace):
    updates = {}
    for name in ("alpha", "beta"):
        entries = (assistant_entry("Alpha-only history", id="alpha-message"),) if name == "alpha" else ()
        journal = write_journal(workspace.project / f"{name}.jsonl", *entries)
        workspace.comms.registry.declare(NativeThread(
            name, frozenset(), Checkout(workspace.project), session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root)))
        read = workspace.comms.transcripts.capture_page_read(name)
        updates[name] = TranscriptSnapshotUpdate(read.read(), read.identity)

    expected = coordination_fact(workspace.comms, "alpha")
    owner = workspace.agents.detached_agent("alpha")
    await owner.comms_consumer_class(owner, owner.session_id).consume_metadata(encode_updates(expected))
    identity = updates["alpha"].identity
    assert owner.controller.session.accepts_snapshot(identity, owner)
    assert not SessionBinding("beta").accepts_snapshot(identity, owner)
    assert not owner.controller.session.accepts_snapshot(
        replace(identity, root=str(workspace.project)), owner)
    assert not owner.controller.session.accepts_snapshot(replace(
        identity, thread=replace(identity.thread, created_at=identity.thread.created_at - 0.5)), owner)

    async with workspace.app(size=(110, 38)) as ui:
        alpha_tab = await ui.app.thread_navigation.open_named(
            owner_mode=ui.selected_tab, project_path=ui.app.project_dir, name="alpha")
        await ui.until(lambda: ui.shows("Alpha-only history"), why="alpha's saved history")

        await ui.app.thread_navigation.open_named(
            owner_mode=alpha_tab, project_path=ui.app.project_dir, name="beta")
        await ui.step()
        beta = ui.detached_agent(None)
        ui.attach_agent(beta)
        assert not beta.controller.session.accepts_notification("alpha")
        await deliver(beta, carrying(expected, updates["alpha"]), session_id="alpha")
        assert beta.coordination is None
        # Publication also refuses foreign work without relying on its envelope.
        await beta.controller.publish_transcript_snapshot(
            updates["alpha"], beta.controller.surface, beta.controller.session)
        await ui.step()
        assert not ui.shows("Alpha-only history")

        await ui.select_tab(alpha_tab)
        await ui.until(lambda: ui.shows("Alpha-only history"), why="alpha's retained tab")
