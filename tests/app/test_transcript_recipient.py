"""A replay belongs to its requested tab, not whichever tab is still opening."""

from dataclasses import replace

from agent_comms.acp_extension import TranscriptSnapshotUpdate

from support.agents import deliver
from support.coordination import carrying, registered_coordination_fact
from support.journals import assistant_entry, write_journal


async def test_unbound_tab_refuses_another_threads_snapshot(workspace):
    updates = {}
    for name, text in (("alpha", "Alpha-only history"), ("beta", "Beta-only history")):
        journal = write_journal(workspace.project / f"{name}.jsonl",
                                assistant_entry(text, id=f"{name}-message"))
        workspace.comms.registry.declare(workspace.comms.registry.new_thread(
            name, frozenset(), str(workspace.project), session_file=str(journal)))
        read = workspace.comms.transcripts.capture_page_read(name)
        updates[name] = TranscriptSnapshotUpdate(read.read(), read.identity)

    async with workspace.app(size=(110, 38)) as ui:
        alpha_tab = ui.selected_tab
        alpha = ui.detached_agent("alpha")
        ui.attach_agent(alpha)
        await deliver(alpha, carrying(
            registered_coordination_fact(workspace.comms, "alpha"), updates["alpha"]))
        await ui.until(lambda: ui.shows("Alpha-only history"), why="alpha's own replay")

        await ui.new_session()
        beta = ui.detached_agent(None)
        ui.attach_agent(beta)
        assert not beta.controller.session.accepts_notification("alpha")
        await deliver(beta, carrying(updates["alpha"]), session_id="alpha")
        # The publication itself also refuses foreign work, even without its envelope.
        await beta.controller.publish_transcript_snapshot(
            updates["alpha"], beta.controller.surface, beta.controller.session)
        await ui.step()
        assert not ui.shows("Alpha-only history")

        beta.session_id = "beta"
        expected = registered_coordination_fact(workspace.comms, "beta")
        await deliver(beta, carrying(expected))
        # A valid outer session ID cannot relabel a different page's witness.
        await deliver(beta, carrying(updates["alpha"]), session_id="beta")
        identity = updates["beta"].identity
        earlier_birth = replace(identity, thread=replace(
            identity.thread, created_at=identity.thread.created_at - 0.5))
        assert not beta.controller.session.accepts_snapshot(earlier_birth, expected)
        await deliver(beta, carrying(updates["beta"]))
        await ui.until(lambda: ui.shows("Beta-only history"), why="beta's own replay")
        assert not ui.shows("Alpha-only history")

        await ui.select_tab(alpha_tab)
        await ui.until(lambda: ui.shows("Alpha-only history"), why="alpha's retained tab")
        assert not ui.shows("Beta-only history")
