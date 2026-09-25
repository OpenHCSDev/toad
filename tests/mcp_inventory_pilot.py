"""Offline, provider-free Pi MCP package inventory projection contract pilot."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from textual.app import App, ComposeResult
from textual.widgets import Static

import toad.mcp_inventory as mcp_inventory
from toad.mcp_inventory import (
    UnsupportedInventory,
    parse_inventory,
    read_inventory,
    render_inventory,
)
from toad.screens.mcp_inventory import MCPInventoryScreen


DIGEST = "a" * 64


def fixture(root: Path) -> dict:
    return {
        "version": 2,
        "projectRoot": str(root),
        "projectTrustedSaved": False,
        "projectConfigSkipped": True,
        "lifetime": "active_pi_turn",
        "live": {"state": "not_running"},
        "declarations": {
            "user": [
                {
                    "id": "fixture",
                    "scope": "user",
                    "digest": DIGEST,
                    "effective": True,
                    "enabled": True,
                    "status": "trust_required",
                    "callPolicy": "unavailable",
                    "transport": {
                        "type": "stdio",
                        "argumentCount": 1,
                        "cwd": "project",
                        "envNames": ["PUBLIC_NAME"],
                        "envFrom": [["CHILD", "HOST"]],
                    },
                }
            ],
            "project": [],
        },
    }


def rejected(data: bytes, root: Path) -> None:
    try:
        parse_inventory(data, root)
    except UnsupportedInventory:
        return
    raise AssertionError("Invalid package inventory accepted")


async def main() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        valid = fixture(root)
        encoded = json.dumps(valid).encode()
        inventory = parse_inventory(encoded, root)
        assert inventory.project_trusted_saved is False
        assert inventory.user[0].status == "trust_required"
        assert inventory.user[0].digest == DIGEST
        display = render_inventory(inventory)
        assert "not live" in display and "next Pi turn" in display
        assert "No MCP action is available" in render_inventory(None)
        assert "PUBLIC_NAME" in display and "HOST" in display
        assert "command" not in display and "approval granted" not in display
        trusted = deepcopy(valid)
        trusted["projectTrustedSaved"] = True
        trusted["projectConfigSkipped"] = False
        trusted["declarations"]["user"][0].update(
            effective=False,
            status="shadowed",
            callPolicy="unavailable",
            executable="do-not-leak-command",
            env="do-not-leak-secret",
        )
        project = deepcopy(valid["declarations"]["user"][0])
        project.update(
            scope="project", effective=True, status="approved", callPolicy="ask"
        )
        trusted["declarations"]["project"] = [project]
        shadowed = parse_inventory(json.dumps(trusted).encode(), root)
        assert shadowed.user[0].status == "shadowed"
        assert shadowed.project[0].call_policy == "ask"
        assert "do-not-leak" not in render_inventory(shadowed)

        rejected(encoded.replace(b'"version": 2', b'"version": 1'), root)
        rejected(encoded.replace(str(root).encode(), b"/some-other-root"), root)
        rejected(encoded.replace(b'"not_running"', b'"running"'), root)
        rejected(encoded.replace(b'"project": []', b'"project": [{}]'), root)
        rejected(encoded.replace(b'"argumentCount": 1', b'"argumentCount": true'), root)
        rejected(
            encoded.replace(b'"status": "trust_required"', b'"status": "approved"'),
            root,
        )
        rejected(encoded.replace(b'"version": 2', b'"version": 2, "version": 2'), root)
        rejected(b'{"version": 2, "declarations":', root)
        rejected(b" " * 128_001, root)

        # An explicit executable path is necessary. Never consult PATH/checkout.
        assert await read_inventory(root, node_path="", cli_path="") is None
        script = root / "fake-package-cli.py"
        script.write_text(
            """\
import json, sys
assert sys.argv[1:4] == ['inventory', '--json', '--project']
assert sys.argv[4] == ROOT
print(json.dumps(DOC))
""".replace("ROOT", repr(str(root))).replace("DOC", repr(valid))
        )
        dto = await read_inventory(root, node_path=sys.executable, cli_path=str(script))
        assert dto == inventory

        class InventoryApp(App):
            def compose(self) -> ComposeResult:
                yield Static("Home")

        app = InventoryApp()
        async with app.run_test(size=(100, 35)) as pilot:
            screen = MCPInventoryScreen(
                root, node_path=sys.executable, cli_path=str(script)
            )
            app.push_screen(screen)
            await pilot.pause(0.1)
            assert app.screen is screen
            assert "fixture" in str(
                screen.query_one("#mcp-inventory-status", Static).content
            )
            screen.dismiss()
            await pilot.pause()
            assert app.screen is not screen

        script.write_text("print('wrong contract')\n")
        assert (
            await read_inventory(root, node_path=sys.executable, cli_path=str(script))
            is None
        )
        script.write_text("import time; time.sleep(1)\n")
        old_timeout = mcp_inventory.INVENTORY_TIMEOUT_SECONDS
        mcp_inventory.INVENTORY_TIMEOUT_SECONDS = 0.02
        try:
            assert (
                await read_inventory(
                    root, node_path=sys.executable, cli_path=str(script)
                )
                is None
            )
        finally:
            mcp_inventory.INVENTORY_TIMEOUT_SECONDS = old_timeout

    print(
        "Pi MCP inventory: explicit CLI, v2 trust/rows, fail-closed malformed/root/live, no authority"
    )


if __name__ == "__main__":
    asyncio.run(main())
