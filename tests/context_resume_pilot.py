"""Saved context is visible on real ACP attachment before any provider prompt."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from agent_comms import Thread, wire
from runtime_fixture import ToadApp


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-context-resume-", dir="/var/tmp") as raw:
        root = Path(raw)
        forbidden = root / "must-not-call-provider"
        forbidden.write_text("#!/bin/sh\ntouch " + str(root / "provider-called") + "\nexit 1\n")
        forbidden.chmod(0o700)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"), AGENT_COMMS_ROOT=str(root / "wire"),
            AGENT_COMMS_AGENT_BIN=str(forbidden), AGENT_COMMS_AGENT_ARGS="",
            AGENT_COMMS_AGENT_MODELS="test/model",
        )
        comms = wire(root / "wire")
        comms.register(Thread("saved", frozenset({"acp"}), str(root)))
        comms.set_agent_info("saved", model="test/model", context_used=38723, context_size=272000)
        app = ToadApp(agent_data={
            "name": "Comms", "identity": "context-replay-test", "short_name": "context",
            "run_command": {"*": f"{sys.executable} -m agent_comms.acp"}, "protocol": "acp",
        }, project_dir=str(root), agent_session_id="saved")
        async with app.run_test(size=(120, 40)) as pilot:
            async with asyncio.timeout(20):
                while (not getattr(app.screen, "conversation", None)
                       or not app.screen.conversation.agent_ready):
                    await asyncio.sleep(0.05)
            await pilot.pause()
            agent = app.screen.conversation.agent
            assert agent._context_usage.used == 38723
            assert agent._context_usage.size == 272000
            assert agent._context_usage_saved is True
            assert "38.7K" in app.screen.conversation.status.plain
            assert "last response" in app.screen.conversation.status.plain
            agent.rpc_session_update("saved", {"sessionUpdate": "usage_update", "used": 40000, "size": 272000})
            await pilot.pause()
            assert agent._context_usage.used == 40000 and not agent._context_usage_saved
            assert "last response" not in app.screen.conversation.status.plain
            agent._publish_coordination_metadata({"_meta": {"agentComms": {
                "thread": "saved", "wireRoot": str(root / "wire"), "contextUsage": None,
            }}})
            await pilot.pause()
            assert agent._context_usage is None
            assert "unavailable" in app.screen.conversation.status.plain
            assert not (root / "provider-called").exists()
            assert app._exception is None
    print("context resume: saved meter restored on actual ACP load, zero provider calls")


if __name__ == "__main__":
    asyncio.run(main())
