"""Real pinned MCP inventory/PTY decisions, isolated trust and no server/provider calls."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from agent_comms.comms import Comms
from textual.widgets import OptionList, Button
from runtime_fixture import ToadApp

from toad.mcp_inventory import read_inventory
from toad.mcp_decision import LocalDecisionPTY
from toad.screens.mcp_inventory import MCPInventoryScreen


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(.02)


async def main():
    package = Path(os.environ["AC_NATIVE_COPIED_PACKAGE"])
    with TemporaryDirectory(prefix="mcp-wire-", dir="/var/tmp") as wire_dir, TemporaryDirectory(prefix="mcp-pinned-") as stage_dir:
        stage = Path(stage_dir)
        project, agent_dir = stage / "project", stage / "pi"
        project.mkdir()
        agent_dir.mkdir()
        comms = Comms(Path(wire_dir) / "wire")
        root_id = comms.messaging.initialize_private_initial_protocol()
        os.environ.update(AGENT_COMMS_ROOT=str(comms.root),
                          AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
                          AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),
                          PI_CODING_AGENT_DIR=str(agent_dir),
                          XDG_CONFIG_HOME=str(stage / "config"),
                          XDG_DATA_HOME=str(stage / "data"),
                          XDG_STATE_HOME=str(stage / "state"))
        os.environ.pop("PI_PROMPT", None)
        setup = r'''
import { pathToFileURL } from 'node:url';
const packageRoot = process.argv[1], projectRoot = process.argv[2], agentDir = process.argv[3];
const { ProjectTrustStore } = await import(pathToFileURL(packageRoot + '/dist/index.js'));
const { writeNativeServer } = await import(pathToFileURL(packageRoot + '/agent-comms-extensions/pi-mcp-client/src/config-write.mjs'));
new ProjectTrustStore(agentDir).set(projectRoot, true);
await writeNativeServer({ agentDir, projectRoot, configDirName: '.pi', scope: 'project',
  declaration: { id: 'fixture', enabled: true, instructionsPolicy: 'status-only',
    transport: { type: 'stdio', command: 'never-launched', args: [], cwd: 'project' } }});
'''
        subprocess.run(["node", "--input-type=module", "-e", setup, str(package), str(project), str(agent_dir)], check=True, timeout=10)
        inventory = await read_inventory(project)
        assert inventory is not None and inventory.project_trusted_saved
        assert inventory.project[0].status == "trust_required"
        app = ToadApp(project_dir=str(project))
        async with app.run_test(size=(110, 42)) as pilot:
            app.screen.action_mcp_inventory()
            await until(lambda: isinstance(app.screen, MCPInventoryScreen))
            screen = app.screen
            await until(lambda: screen._inventory is not None)
            listing = screen.query_one(OptionList)
            listing.highlighted = 0
            await pilot.pause()
            assert not screen.query_one("#trust_approve", Button).disabled
            assert screen.query_one("#calls_allow", Button).disabled
            await screen.dismiss()
            assert app._exception is None
        print("PASS: mounted inventory reads verified pinned package, positive action available without negotiation", flush=True)
        pty = LocalDecisionPTY()

        async def decide(snapshot, action, decision, *, cancel=False):
            row = snapshot.project[0]
            appeared = asyncio.Event()
            visible = True
            output = []

            async def show(text):
                output.append(text)
                if " to apply:" in "".join(output):
                    appeared.set()

            task = asyncio.create_task(pty.run(inventory=snapshot, row=row, action=action,
                decision=decision, show=show, controller_visible=lambda: visible))
            try:
                await asyncio.wait_for(appeared.wait(), 12)
                assert not task.done()
                if cancel:
                    visible = False
                    pty.stop()
                    assert await asyncio.wait_for(task, 5) == "controller_lost"
                else:
                    # Synthetic user input goes through the same public PTY input path.
                    await pty.write_user_input(f"{decision}:{row.id}:{row.digest}\n")
                    assert await asyncio.wait_for(task, 5) == "exited_zero", output
                    assert json.loads("".join(output).splitlines()[-1])["applied"] is True, output
            finally:
                pty.stop()
                await asyncio.gather(task, return_exceptions=True)
            assert pty._process is None and pty._master is None

        await decide(inventory, "trust", "approve")
        approved = await read_inventory(project)
        assert approved.project[0].status == "approved"
        await decide(approved, "calls", "allow")
        allowed = await read_inventory(project)
        assert allowed.project[0].call_policy == "allow"
        await decide(allowed, "calls", "ask")
        ask = await read_inventory(project)
        assert ask.project[0].call_policy == "ask"
        await decide(ask, "trust", "deny")
        denied = await read_inventory(project)
        assert denied.project[0].status == "denied"

        async def unused_show(text):
            raise AssertionError("Stale action launched a child")

        assert await pty.run(inventory=approved, row=approved.project[0], action="calls",
            decision="allow", show=unused_show, controller_visible=lambda: True) == "stale_snapshot"
        await decide(denied, "trust", "approve", cancel=True)
        assert (await read_inventory(project)).project[0].status == "denied"
        print("PASS: actual package approve/allow/ask/deny receipts, stale refusal and controller cancellation; children reaped", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
