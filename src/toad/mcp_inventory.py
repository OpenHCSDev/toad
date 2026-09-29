"""Read-only projection of the installed Pi MCP package's version-2 CLI inventory.

This module never reads MCP config/ledgers or decides approval. Inventory comes
from the Comms-owned pinned package and does not imply an active Pi session.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from agent_comms.field_codec import FieldCodec
from toad.mcp_declarations import Inventory


MAX_INVENTORY_BYTES = 128_000
INVENTORY_TIMEOUT_SECONDS = 5.0


class UnsupportedInventory(ValueError):
    """The CLI output violates the current package-owned inventory contract."""


def parse_inventory(data: bytes, expected_root: Path) -> Inventory:
    """Decode the exact package record once; trust declared fields thereafter."""
    if len(data) > MAX_INVENTORY_BYTES:
        raise UnsupportedInventory("Oversized inventory")

    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise UnsupportedInventory("Duplicate inventory field")
            value[key] = item
        return value

    try:
        inventory = FieldCodec.decode(Inventory, json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs))
        if inventory.project_root != str(expected_root.resolve(strict=True)):
            raise UnsupportedInventory("Project root mismatch")
        return inventory
    except (UnicodeError, ValueError, TypeError, OSError) as error:
        raise UnsupportedInventory(str(error)) from error


def installed_mcp_command() -> tuple[str, str]:
    """Use MCP shipped inside the same verified native package as Comms."""
    from agent_comms.native_pi import NativePiRpcLaunch

    package = NativePiRpcLaunch.package_for_command("pi")
    node = shutil.which("node")
    if node is None:
        raise FileNotFoundError("Node is unavailable")
    cli = package / "agent-comms-extensions/pi-mcp-client/bin/pi-mcp.mjs"
    if not cli.is_file():
        raise FileNotFoundError("The pinned native package has no MCP CLI")
    return str(Path(node).resolve(strict=True)), str(cli)


async def read_inventory(project_root: Path) -> Inventory | None:
    """Read the pinned package's static inventory without starting servers."""
    try:
        node, cli = await asyncio.to_thread(installed_mcp_command)
    except (OSError, ValueError, RuntimeError):
        return None
    process: asyncio.subprocess.Process | None = None
    try:
        root = project_root.resolve(strict=True)
        env = os.environ.copy()
        # Node flags/module search must not be injected by the project shell.
        env.pop("NODE_OPTIONS", None)
        env.pop("NODE_PATH", None)
        process = await asyncio.create_subprocess_exec(
            str(node),
            str(cli),
            "inventory",
            "--json",
            "--project",
            str(root),
            cwd=str(Path(cli).parent),
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout = process.stdout
        assert stdout is not None

        async def receive() -> bytes:
            output = await stdout.read(MAX_INVENTORY_BYTES + 1)
            if len(output) > MAX_INVENTORY_BYTES:
                raise UnsupportedInventory("Oversized CLI output")
            await process.wait()
            return output

        data = await asyncio.wait_for(receive(), INVENTORY_TIMEOUT_SECONDS)
        if process.returncode != 0:
            return None
        return parse_inventory(data, root)
    except OSError, TimeoutError, UnsupportedInventory:
        return None
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


def render_inventory(inventory: Inventory | None) -> str:
    """Display only typed, redacted package fields; no authority inference."""
    if inventory is None:
        return (
            "MCP package inventory unavailable or unsupported.\n"
            "The current Comms native package must provide its MCP CLI.\n"
            "No MCP action is available here."
        )
    return inventory.render()
