from comms_boundary_fixture import coordination_fact

from toad.widgets.conversation import Conversation

"Saved context is visible on real ACP attachment before any provider prompt."
import asyncio
import os
import sys
import tempfile
from pathlib import Path

from agent_comms.threads import Thread
from runtime_fixture import ToadApp, private_native_wire


async def main():
    with tempfile.TemporaryDirectory(
        prefix="toad-context-resume-", dir="/var/tmp"
    ) as raw:
        root = Path(raw)
        forbidden = root / "must-not-call-provider"
        forbidden.write_text(
            "#!/bin/sh\ntouch " + str(root / "provider-called") + "\nexit 1\n"
        )
        forbidden.chmod(448)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            AGENT_COMMS_ROOT=str(root / "wire"),
            AGENT_COMMS_AGENT_BIN="pi",
            AGENT_COMMS_AGENT_ARGS="",
            AGENT_COMMS_AGENT_MODELS="test/model",
        )
        comms = private_native_wire(root / "wire")
        comms.registry.declare(Thread("saved", frozenset({"acp"}), str(root)))
        comms.agents.set_agent_info(
            "saved", model="test/model", context_used=38723, context_size=272000
        )
        app = ToadApp(
            agent_data={
                "name": "Comms",
                "identity": "context-replay-test",
                "short_name": "context",
                "run_command": {"*": f"{sys.executable} -m agent_comms.acp"},
                "protocol": "acp",
            },
            project_dir=str(root),
            agent_session_id="saved",
        )
        async with app.run_test(size=(120, 40)) as pilot:
            async with asyncio.timeout(20):
                while (
                    not app.screen.query_one_optional(Conversation)
                    or not app.selected_session.conversation.agent_ready
                ):
                    await asyncio.sleep(0.05)
            await pilot.pause()
            agent = app.selected_session.conversation.agent
            assert agent.context_measurement.used == 38723
            assert agent.context_measurement.size == 272000
            assert agent.context_measurement.source_label == "last response"
            assert "38.7K" in app.selected_session.conversation.status.plain
            assert "last response" in app.selected_session.conversation.status.plain
            agent.rpc_session_update(
                "saved",
                {"sessionUpdate": "usage_update", "used": 40000, "size": 272000},
            )
            await pilot.pause()
            assert agent.context_measurement.used == 40000 and (
                agent.context_measurement.source_label == ""
            )
            assert "last response" not in app.selected_session.conversation.status.plain
            agent.comms_consumer_class(agent, agent.session_id).dispatch_sync(
                coordination_fact("saved", str(root / "wire"), context_usage=None)
            )
            await pilot.pause()
            assert not agent.context_measurement.available
            assert "unavailable" in app.selected_session.conversation.status.plain
            assert not (root / "provider-called").exists()
            assert app._exception is None
    print(
        "context resume: saved meter restored on actual ACP load, zero provider calls"
    )


if __name__ == "__main__":
    asyncio.run(main())
