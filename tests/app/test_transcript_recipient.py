"""A replay belongs to its requested tab, not whichever tab is still opening."""

from agent_comms.repo import Checkout
from agent_comms.session_file import RegistrySessionLocation
from dataclasses import replace

from agent_comms.acp_extension import TranscriptSnapshotUpdate
from agent_comms.nominal.field_codec import AcpSessionId
from agent_comms.threads import Thread
from toad.acp.agent_controller import BoundSessionBinding, SessionBinding
from toad.acp.coordination_attachment import CoordinatedThread

from support.agents import deliver
from support.coordination import carrying, registered_coordination_fact
from support.journals import assistant_entry, write_journal


async def test_unbound_tab_refuses_another_threads_snapshot(workspace):
    updates = {}
    for name in ("alpha", "beta"):
        entries = (assistant_entry("Alpha-only history", id="alpha-message"),) if name == "alpha" else ()
        journal = write_journal(workspace.project / f"{name}.jsonl", *entries)
        workspace.comms.registry.declare(Thread(
            name, frozenset(), Checkout(workspace.project), session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root)))
        read = workspace.comms.transcripts.capture_page_read(name)
        updates[name] = TranscriptSnapshotUpdate(read.read(), read.identity)

    expected = registered_coordination_fact(workspace.comms, "alpha")
    attachment = CoordinatedThread(expected)
    identity = updates["alpha"].identity
    destination = AcpSessionId("original-acp-destination")
    assert BoundSessionBinding(destination).accepts_snapshot(identity, attachment, destination)
    assert not BoundSessionBinding(AcpSessionId("beta")).accepts_snapshot(identity, attachment, destination)
    assert not SessionBinding().accepts_snapshot(identity, attachment, destination)
    assert not BoundSessionBinding(destination).accepts_snapshot(
        replace(identity, root=str(workspace.project)), attachment, destination)
    assert not BoundSessionBinding(destination).accepts_snapshot(replace(
        identity, thread=replace(identity.thread, created_at=identity.thread.created_at - 0.5)),
        attachment, destination)

    async with workspace.app(size=(110, 38)) as ui:
        alpha_tab = await ui.app.thread_navigation.open(
            owner_mode=ui.selected_tab, project_path=ui.app.project_dir, target="alpha")
        await ui.until(lambda: ui.shows("Alpha-only history"), why="alpha's saved history")

        await ui.app.thread_navigation.open(
            owner_mode=alpha_tab, project_path=ui.app.project_dir, target="beta")
        await ui.step()
        beta = ui.detached_agent(None)
        ui.attach_agent(beta)
        assert not beta.controller.session.accepts_notification("alpha")
        await deliver(beta, carrying(expected, updates["alpha"]), session_id="alpha")
        assert not beta.presentation.queue_supported
        # Publication also refuses foreign work without relying on its envelope.
        await beta.controller.publish_transcript_snapshot(
            updates["alpha"], beta.controller.surface, beta.controller.session,
            destination=AcpSessionId("alpha"))
        await ui.step()
        assert not ui.shows("Alpha-only history")

        await ui.select_tab(alpha_tab)
        await ui.until(lambda: ui.shows("Alpha-only history"), why="alpha's retained tab")


async def test_bound_acp_destination_accepts_its_different_canonical_history(workspace):
    journal = write_journal(
        workspace.project / "canonical-history.jsonl",
        assistant_entry("CANONICAL_HISTORY_ON_ORIGINAL_DESTINATION", id="canonical-answer"),
    )
    workspace.comms.registry.declare(Thread(
        "canonical-history", frozenset(), Checkout(workspace.project),
        session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root),
    ))
    read = workspace.comms.transcripts.capture_page_read("canonical-history")
    snapshot = TranscriptSnapshotUpdate(read.read(), read.identity)
    expected = registered_coordination_fact(workspace.comms, "canonical-history")
    destination = "original-acp-destination"
    async with workspace.app(size=(110, 38)) as ui:
        agent = ui.detached_agent(destination)
        ui.attach_agent(agent)
        await deliver(agent, carrying(expected, snapshot), session_id=destination)
        await ui.until(
            lambda: ui.shows("CANONICAL_HISTORY_ON_ORIGINAL_DESTINATION"),
            why="canonical history painted only on its original ACP recipient",
        )
        assert agent.controller.session.accepts_notification(destination)
        assert snapshot.identity.requested_name != destination
        assert agent.coordination_attachment.accepts_read(snapshot.identity)
