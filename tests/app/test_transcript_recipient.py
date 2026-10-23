"""A replay belongs to its requested tab, not whichever tab is still opening."""

from agent_comms.session_file import RegistrySessionLocation
from dataclasses import replace

from agent_comms.acp_extension import TranscriptSnapshotUpdate
from toad.acp.agent_controller import SessionBinding

from support.agents import deliver
from support.coordination import carrying, registered_coordination_fact
from support.journals import assistant_entry, write_journal


async def test_unbound_tab_refuses_another_threads_snapshot(workspace):
    updates = {}
    for name in ("alpha", "beta"):
        entries = (assistant_entry("Alpha-only history", id="alpha-message"),) if name == "alpha" else ()
        journal = write_journal(workspace.project / f"{name}.jsonl", *entries)
        workspace.comms.registry.declare(workspace.comms.registry.new_thread(
            name, frozenset(), str(workspace.project), session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root)))
        read = workspace.comms.transcripts.capture_page_read(name)
        updates[name] = TranscriptSnapshotUpdate(read.read(), read.identity)

    expected = registered_coordination_fact(workspace.comms, "alpha")
    identity = updates["alpha"].identity
    assert SessionBinding("alpha").accepts_snapshot(identity, expected)
    assert not SessionBinding("beta").accepts_snapshot(identity, expected)
    assert not SessionBinding("alpha").accepts_snapshot(
        replace(identity, root=str(workspace.project)), expected)
    assert not SessionBinding("alpha").accepts_snapshot(replace(
        identity, thread=replace(identity.thread, created_at=identity.thread.created_at - 0.5)), expected)

    async with workspace.app(size=(110, 38)) as ui:
        alpha_tab = await ui.app.thread_navigation.open(
            owner_mode=ui.selected_tab, project_path=workspace.project, target="alpha")
        await ui.until(lambda: ui.shows("Alpha-only history"), why="alpha's saved history")

        await ui.app.thread_navigation.open(
            owner_mode=alpha_tab, project_path=workspace.project, target="beta")
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
