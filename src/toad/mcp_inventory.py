"""Read-only projection of the installed Pi MCP package's version-2 CLI inventory.

This module never reads MCP config/ledgers or decides approval. A configured
executable is a user-selected local program, not proof of an active Pi session.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any


MAX_INVENTORY_BYTES = 128_000
INVENTORY_TIMEOUT_SECONDS = 5.0
_ID = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_ENV = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
_STATUSES = {
    "approved",
    "disabled",
    "denied",
    "trust_required",
    "unsupported_env",
    "shadowed",
}
_POLICIES = {"allow", "ask", "unavailable"}


class UnsupportedInventory(ValueError):
    """The CLI's output is not the versioned package projection we support."""


@dataclass(frozen=True)
class Declaration:
    id: str
    scope: str
    digest: str
    effective: bool
    enabled: bool
    status: str
    call_policy: str
    argument_count: int
    env_names: tuple[str, ...]
    env_from: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Inventory:
    project_root: Path
    project_trusted_saved: bool
    project_config_skipped: bool
    user: tuple[Declaration, ...]
    project: tuple[Declaration, ...]


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UnsupportedInventory("Expected object")
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise UnsupportedInventory("Expected boolean")
    return value


def _rows(value: object, scope: str) -> tuple[Declaration, ...]:
    if not isinstance(value, list) or len(value) > 256:
        raise UnsupportedInventory("Invalid declarations")
    rows: list[Declaration] = []
    seen: set[str] = set()
    for raw in value:
        row = _object(raw)
        identifier, digest = row.get("id"), row.get("digest")
        if (
            not isinstance(identifier, str)
            or not _ID.fullmatch(identifier)
            or identifier in seen
            or not isinstance(digest, str)
            or not _DIGEST.fullmatch(digest)
            or row.get("scope") != scope
        ):
            raise UnsupportedInventory("Invalid declaration identity")
        seen.add(identifier)
        status, policy = row.get("status"), row.get("callPolicy")
        if status not in _STATUSES or policy not in _POLICIES:
            raise UnsupportedInventory("Unsupported declaration state")
        effective = _boolean(row.get("effective"))
        enabled = _boolean(row.get("enabled"))
        if (
            (not effective and (status != "shadowed" or policy != "unavailable"))
            or (effective and status == "shadowed")
            or (status != "approved" and policy != "unavailable")
        ):
            raise UnsupportedInventory("Inconsistent declaration state")
        transport = _object(row.get("transport"))
        argument_count = transport.get("argumentCount")
        if (
            transport.get("type") != "stdio"
            or transport.get("cwd") != "project"
            or type(argument_count) is not int
            or not 0 <= argument_count <= 256
        ):
            raise UnsupportedInventory("Unsupported transport summary")
        names, from_pairs = transport.get("envNames"), transport.get("envFrom")
        if (
            not isinstance(names, list)
            or len(names) > 128
            or any(
                not isinstance(name, str) or not _ENV.fullmatch(name) for name in names
            )
            or len(set(names)) != len(names)
            or not isinstance(from_pairs, list)
            or len(from_pairs) > 128
        ):
            raise UnsupportedInventory("Invalid environment summary")
        pairs: list[tuple[str, str]] = []
        for pair in from_pairs:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or any(
                    not isinstance(item, str) or not _ENV.fullmatch(item)
                    for item in pair
                )
            ):
                raise UnsupportedInventory("Invalid environment mapping")
            pairs.append((pair[0], pair[1]))
        if len(set(name for name, _ in pairs)) != len(pairs):
            raise UnsupportedInventory("Duplicate environment mapping")
        rows.append(
            Declaration(
                identifier,
                scope,
                digest,
                effective,
                enabled,
                status,
                policy,
                argument_count,
                tuple(names),
                tuple(pairs),
            )
        )
    return tuple(rows)


def parse_inventory(data: bytes, expected_root: Path) -> Inventory:
    """Accept only a bounded, exact-version, canonical-root static DTO."""
    if len(data) > MAX_INVENTORY_BYTES:
        raise UnsupportedInventory("Oversized inventory")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise UnsupportedInventory("Duplicate inventory field")
            value[key] = item
        return value

    try:
        doc = _object(json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs))
        if type(doc.get("version")) is not int or doc["version"] != 2:
            raise UnsupportedInventory("Unsupported inventory version")
        root = doc.get("projectRoot")
        if not isinstance(root, str) or root != str(expected_root.resolve(strict=True)):
            raise UnsupportedInventory("Project root mismatch")
        trusted = _boolean(doc.get("projectTrustedSaved"))
        skipped = _boolean(doc.get("projectConfigSkipped"))
        if (
            doc.get("lifetime") != "active_pi_turn"
            or _object(doc.get("live")).get("state") != "not_running"
        ):
            raise UnsupportedInventory("Unsupported live status")
        declarations = _object(doc.get("declarations"))
        user = _rows(declarations.get("user"), "user")
        project = _rows(declarations.get("project"), "project")
        if not trusted and (project or any(row.status == "approved" for row in user)):
            raise UnsupportedInventory("Approval without saved project trust")
        effective_ids = [row.id for row in (*user, *project) if row.effective]
        if len(set(effective_ids)) != len(effective_ids):
            raise UnsupportedInventory("Multiple effective declarations")
        return Inventory(
            expected_root.resolve(strict=True), trusted, skipped, user, project
        )
    except (UnicodeError, json.JSONDecodeError, TypeError, KeyError, OSError) as error:
        raise UnsupportedInventory("Invalid inventory") from error


async def read_inventory(
    project_root: Path, *, node_path: str, cli_path: str
) -> Inventory | None:
    """Call only the explicitly selected local installed package, never PATH or a checkout.

    None denotes missing/unconfigured CLI or an unreadable/unavailable projection.
    A returned DTO is still only a static declaration snapshot, not live state.
    """
    node, cli = Path(node_path), Path(cli_path)
    if (
        not node_path
        or not cli_path
        or not node.is_absolute()
        or not cli.is_absolute()
        or not node.is_file()
        or not cli.is_file()
    ):
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
            cwd=str(cli.parent),
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
            "Configure absolute Node and installed Pi MCP CLI paths in Toad settings.\n"
            "No MCP action is available here."
        )
    lines = [
        "Pi MCP declarations · static package snapshot (not live)",
        f"Saved Pi project trust: {'yes' if inventory.project_trusted_saved else 'no'}",
        f"Project config skipped before trust: {'yes' if inventory.project_config_skipped else 'no'}",
        "Runtime: not running in this snapshot; live status is not asserted.",
        "Decisions apply to the next Pi turn. This is not active server state.",
        "Actions launch the installed package CLI in a visible POSIX PTY; it owns",
        "the complete display, exact digest challenge and ledger write. Toad never",
        "auto-answers and cannot undo a decision the package already committed.",
        "Positive grants additionally require the pinned supported CLI SHA-256",
        "(settings); older or changed builds refuse Approve/Allow but keep",
        "Deny/Require-asks available.",
    ]
    for scope, rows in (("User", inventory.user), ("Project", inventory.project)):
        lines.append(f"\n{scope} declarations ({len(rows)}):")
        for row in rows:
            lines.append(
                f"  {row.id} · {row.status} · calls {row.call_policy}"
                f" · {'effective' if row.effective else 'shadowed'}"
            )
            lines.append(f"    SHA-256: {row.digest}")
            lines.append(
                f"    stdio / project cwd · args {row.argument_count}"
                f" · env names {', '.join(row.env_names) or '(none)'}"
                f" · envFrom {', '.join(f'{name}={source}' for name, source in row.env_from) or '(none)'}"
            )
    return "\n".join(lines)
