"""Current core activity reaches DM/native views without starting a provider."""

from toad.navigation_target import DirectTarget

import asyncio
import os
from pathlib import Path
import tempfile

from agent_comms.activity import ActivityState
from agent_comms.comms import wire
from agent_comms.child_process import ProcessIdentity
from agent_comms.threads import Thread
from runtime_fixture import ToadApp
from toad import messages
from toad.acp.agent import Agent
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.observed_thread_activity import ObservedThreadActivity


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(.02)


async def main():
    with tempfile.TemporaryDirectory(prefix="observed-thread-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        comms.threads.register(Thread("peer", frozenset({"comms"}), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            native = app.screen.conversation
            observed = native.query_one(ObservedThreadActivity)
            assert not observed.display, "Non-Comms idle view must not gain a blank line"
            agent = Agent(root, {"name": "Observed fixture", "identity": "fixture",
                                 "run_command": {"*": "true"}}, "fixture")
            agent._coordination_root, agent._coordination_thread = str(comms.root), "peer"
            agent._message_target = native
            native.set_reactive(type(native).agent, agent)
            owner = app.current_mode
            tracker = app.session_tracker.sessions[owner]
            for detail in ("Checking #comms message", "Responding in #comms"):
                comms.agents.set_activity("peer", ActivityState.THINKING, detail)
                await until(lambda: observed.presentation is not None and detail in observed.presentation.summary)
                native.post_message(messages.SessionUpdate(state="idle", summary="Ready"))
                await pilot.pause()
                assert observed.display and observed.has_class("-working")
                assert tracker.state == "busy" and detail in tracker.summary
                assert native._managed_turn_id is None and native.turn != "agent"
            comms.agents.set_activity("peer", ActivityState.IDLE)
            await until(lambda: observed.presentation is not None and not observed.presentation.busy)
            await pilot.pause()
            assert tracker.state == "idle" and tracker.summary == "Ready"
            comms.threads.register(Thread("dm-peer", frozenset({"comms"}), str(root), process_identity=ProcessIdentity.capture(os.getpid())))
            await app.open_comms_session(owner_mode=owner, project_path=root, me="peer", target=DirectTarget("dm-peer"))
            dm = app.screen.query_one(CommsChatView)
            observed = dm.query_one(ObservedThreadActivity)
            for detail in ("Checking #comms message", "Responding in #comms"):
                comms.agents.set_activity("dm-peer", ActivityState.THINKING, detail)
                await until(lambda: observed.presentation is not None and detail in observed.presentation.summary)
                assert detail in str(observed.render()) and observed.has_class("-working")
            comms.agents.set_activity("dm-peer", ActivityState.IDLE)
            await until(lambda: observed.presentation is not None and not observed.presentation.busy)
            assert str(observed.render()) == "Ready"
        print("PASS: actual registry/activity/core ThreadView -> ACP reader/native conversation and DM; Checking/Responding target, Ready override and idle recovery; no provider/process launch")


if __name__ == "__main__":
    asyncio.run(main())
