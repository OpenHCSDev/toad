"""Offline, provider-free Pi MCP package inventory projection contract pilot."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from toad.mcp_inventory import (
    UnsupportedInventory,
    parse_inventory,
    render_inventory,
)


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
        assert inventory.user[0].status.declared_name == "trust_required"
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
        assert shadowed.user[0].status.declared_name == "shadowed"
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

    print("MCP inventory: current strict DTO, redaction, trust and malformed input rejection pass")


if __name__ == "__main__":
    asyncio.run(main())
