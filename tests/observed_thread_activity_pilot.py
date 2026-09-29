"""Current core activity reaches DM/native views without starting a provider."""

from toad.navigation_target import DirectTarget

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms.activity import ActivityState, UnavailableDrainDiagnostic
from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import wire
from agent_comms.threads import Thread
from comms_boundary_fixture import attach_coordination
from runtime_fixture import ToadApp

from toad import messages
from toad.acp.agent import Agent
from toad.screens.session_view import SessionView
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.observed_thread_activity import ObservedThreadActivity
from toad.widgets.session_details import SessionDetails


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.02)


async def main():
    with tempfile.TemporaryDirectory(prefix="observed-thread-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
        )
        comms = wire(root / "wire")
        comms.threads.register(
            Thread(
                "peer",
                frozenset({"comms"}),
                str(root),
                process_identity=ProcessIdentity.capture(os.getpid()),
            )
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            native = app.selected_session.conversation
            observed = native.query_one(ObservedThreadActivity)
            assert not observed.display, (
                "Non-Comms idle view must not gain a blank line"
            )
            agent = Agent(
                root,
                {
                    "name": "Observed fixture",
                    "identity": "fixture",
                    "run_command": {"*": "true"},
                },
                "fixture",
            )
            agent.attach_surface(native)
            attach_coordination(agent, str(comms.root), "peer")
            native.set_reactive(type(native).agent, agent)
            owner = app.selected_mode
            tracker = app.session_tracker.sessions[owner]
            for detail in ("Checking #comms message", "Responding in #comms"):
                comms.agents.set_activity("peer", ActivityState.THINKING, detail)
                await until(
                    lambda: (
                        observed.presentation is not None
                        and detail in observed.presentation.summary
                    )
                )
                native.post_message(
                    messages.SessionUpdate(state="idle", summary="Ready")
                )
                await pilot.pause()
                assert observed.display and observed.has_class("-working")
                assert tracker.state == "busy" and detail in tracker.summary
                assert native.turns.managed_id is None and not native.turns.owner.busy
            comms.agents.set_activity("peer", ActivityState.IDLE)
            await until(
                lambda: (
                    observed.presentation is not None
                    and (not observed.presentation.busy)
                )
            )
            await pilot.pause()
            assert tracker.state == "idle" and tracker.summary == "Ready"
            identity = comms.registry.snapshot().owner_identity("peer")
            failure = UnavailableDrainDiagnostic(identity, "SchemaVersionError", "cohort schema missing")
            comms.agents.set_drain_diagnostic("peer", identity, failure)
            await until(lambda: observed.presentation is not None and observed.presentation.attention)
            native.post_message(messages.SessionUpdate(state="idle", summary="Ready"))
            await pilot.pause()
            assert tracker.state == "idle" and "Inbox unavailable" in tracker.summary
            assert observed.has_class("-unavailable") and not observed.has_class("-working")
            details = native.query_one(SessionDetails)
            assert details.has_class("-attention") and "Inbox unavailable" in str(details.title)
            comms.agents.set_drain_diagnostic("peer", identity, None)
            await until(lambda: observed.presentation is not None and not observed.presentation.attention)
            await pilot.pause()
            assert tracker.summary == "Ready" and not details.has_class("-attention")
            comms.threads.register(Thread("dm-peer", frozenset({"comms"}), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
            await app.open_comms_session(owner_mode=owner, project_path=root, me="peer", target=DirectTarget("dm-peer"))
            dm = app.screen.query_one(CommsChatView)
            observed = dm.query_one(ObservedThreadActivity)
            for detail in ("Checking #comms message", "Responding in #comms"):
                comms.agents.set_activity("dm-peer", ActivityState.THINKING, detail)
                await until(
                    lambda: (
                        observed.presentation is not None
                        and detail in observed.presentation.summary
                    )
                )
                assert detail in str(observed.render()) and observed.has_class(
                    "-working"
                )
            comms.agents.set_activity("dm-peer", ActivityState.IDLE)
            await until(
                lambda: (
                    observed.presentation is not None
                    and (not observed.presentation.busy)
                )
            )
            assert str(observed.render()) == "Ready"
            identity = comms.registry.snapshot().owner_identity("dm-peer")
            comms.agents.set_drain_diagnostic("dm-peer", identity,
                UnavailableDrainDiagnostic(identity, "OperationalError", "no such table: cohort_schema_meta"))
            await until(lambda: observed.presentation is not None and observed.presentation.attention)
            assert "no such table" in str(observed.render()) and observed.has_class("-unavailable")
            comms.agents.set_drain_diagnostic("dm-peer", identity, None)
            await until(lambda: observed.presentation is not None and not observed.presentation.attention)
            assert str(observed.render()) == "Ready"
            # All logical tabs share the active native WorkspaceScreen. A
            # hidden DM must not keep reading/publishing just because that
            # frame remains active. Instrument the real request callbacks;
            # keep their implementations and the actual stores unchanged.
            hidden_reads = []
            original_read = observed.read
            original_request = dm._history_request

            async def counted_read():
                hidden_reads.append("activity")
                return await original_read()

            def counted_request():
                hidden_reads.append("history")
                return original_request()

            await app.select_session(owner)
            if observed._read_task is not None:
                await observed._read_task
            observed.read = counted_read
            dm._history_request = counted_request
            observed.refresh_observation()
            await dm._refresh()
            await pilot.pause()
            assert hidden_reads == [], hidden_reads
            await app.select_session(dm.query_ancestor(SessionView).mode_name)
            observed.refresh_observation()
            await until(lambda: "activity" in hidden_reads)

        print(
            "PASS: actual registry/activity/core ThreadView -> ACP reader/native conversation and DM; Checking/Responding target, Ready override and idle recovery; no provider/process launch"
        )


if __name__ == "__main__":
    asyncio.run(main())
