"""Real runtime owner -> ACP update -> mounted unresolved-delivery inspector."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.acp import CommsAgent
from agent_comms.operations import wire
from agent_comms.runtime import RuntimeProxy, socket_path
from textual.widgets import Static

from toad.acp.agent import Agent
from toad.app import ToadApp
from toad.widgets.input_delivery import InputDeliveryBar, InputDeliveryDetails


async def main():
    with TemporaryDirectory(prefix="toad-delivery-owner-", dir="/var/tmp") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
            AGENT_COMMS_AGENT_MODELS="openrouter/fake",
        )
        comms = wire(root / "wire")
        project = root / "project"
        project.mkdir()
        owner = CommsAgent(comms, agent_bin="pi", agent_args=["--provider", "openrouter", "--model", "fake"], runtime_enabled=True, auto_wake=False)
        proxy = None
        try:
            session = (await owner.new_session(cwd=str(project))).session_id
            store = owner._dispositions
            # Unresolved channel admission predates this subscriber.
            store.record("bus:7", seq=7, owner=session, admission=1, target="#review", text="Please inspect [this] exact change")
            store.record("bus:8", seq=8, owner="another-owner", admission=1, target="#review", text="Not this owner")
            agent = Agent(project, {"name": "agent-comms", "run_command": {"*": "true"}}, None)
            agent._coordination_root = str(comms.root)
            agent._coordination_thread = session
            app = ToadApp(project_dir=str(project))
            async with app.run_test(size=(110, 35)) as pilot:
                await pilot.pause()
                conversation = app.screen.conversation
                conversation.set_reactive(type(conversation).agent, agent)
                agent.post_message = conversation.post_message

                class Subscriber:
                    async def session_update(self, *, session_id, update):
                        agent.rpc_session_update(session_id, update)

                observer = CommsAgent(comms)
                observer.on_connect(Subscriber())
                proxy = RuntimeProxy(observer, session, socket_path(comms.root, os.getpid()))
                metadata = await proxy.subscribe()
                agent._publish_coordination_metadata({"_meta": metadata}, initial=True)
                await pilot.pause()
                rows = await agent.get_unresolved_inputs()  # actual Unix RuntimeServer
                assert len(rows) == 1 and rows[0]["sequence"] == 7
                assert conversation.unresolved_inputs == rows
                bar = conversation.query_one(InputDeliveryBar)
                assert bar.display
                assert "1 input(s)" in str(bar.query_one(Static).render())
                await pilot.click("#delivery-inspect")
                await pilot.pause()
                assert isinstance(app.screen, InputDeliveryDetails)
                records = app.screen.query_one("#delivery-records", Static)
                assert "Sequence: 7 · Target: #review" in str(records.render()), (str(records.render()), app.screen.inputs, conversation.unresolved_inputs)
                assert "Please inspect [this] exact change" in str(records.render())
                assert app.screen.query_one("#delivery-log")
                original_read = agent.get_unresolved_inputs
                captured, release = asyncio.Event(), asyncio.Event()
                reads = 0

                async def delayed_read():
                    nonlocal reads
                    reads += 1
                    result = await original_read()
                    if reads == 1:
                        captured.set()
                        await release.wait()
                    return result

                agent.get_unresolved_inputs = delayed_read
                refresh = asyncio.create_task(conversation.refresh_input_dispositions())
                await captured.wait()
                # Bound native receipt resolves the owner ledger while the inspector is open.
                native_id = "a" * 32
                assert store.bind("bus:7", admission=1, turn_id="turn", native_id=native_id, text="native prompt")
                assert store.started("bus:7", turn_id="turn", native_id=native_id, text="native prompt")
                previous = conversation._delivery_refresh_revision
                await owner._emit_input_disposition(session, store.get("bus:7"))
                async with asyncio.timeout(2):
                    while conversation._delivery_refresh_revision == previous:
                        await asyncio.sleep(0.01)
                release.set()
                await refresh
                await pilot.pause()
                assert reads == 2
                agent.get_unresolved_inputs = original_read
                assert conversation.unresolved_inputs == []
                assert not bar.display
                assert "No unresolved inputs." in str(records.render())
                # Late UNKNOWN notification invalidates, never restores a resolved row.
                old = dict(store.get("bus:7"), status="unknown")
                await owner._emit_input_disposition(session, old)
                await pilot.pause()
                assert conversation.unresolved_inputs == []
                assert store.status("bus:7") == "started"
        finally:
            if proxy is not None:
                await proxy.close()
            await owner.shutdown()
    print("delivery owner: late attach, owner filtering, exact text, inspector, STARTED removal and stale notification pass")


if __name__ == "__main__":
    asyncio.run(main())
