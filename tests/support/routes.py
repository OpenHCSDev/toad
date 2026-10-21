"""The default comms route a test controls: private roots, and the file that selects one."""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_comms.active_route import ActiveRoute


def private_root(path: Path, project: Path, message: str) -> tuple[Path, str]:
    """A private wire at `path` holding `message` in #team from `peer`; returns it and its root id."""
    from agent_comms.comms import Comms
    from agent_comms.thread_identity import UserThreadRole

    path.mkdir(mode=0o700)
    comms = Comms(path)
    root_id = comms.messaging.initialize_private_initial_protocol()
    comms.registry.declare(comms.registry.new_thread("user", frozenset(), str(project), role=UserThreadRole))
    comms.registry.declare(comms.registry.new_thread("owner", frozenset({"team"}), str(project / "owner-project")))
    comms.registry.declare(comms.registry.new_thread("peer", frozenset({"team"}), str(project / "peer-project")))
    comms.messaging.send("peer", "#team", message)
    return path, root_id


def publish_route(home: Path, root: Path, root_id: str) -> Path:
    """Replace the default-route file under `home` so it selects `root`; returns the file."""
    directory = home / ".local/state/agent-comms"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    destination = directory / "active-route.json"
    replacement = directory / "replacement.json"
    replacement.write_text(json.dumps(ActiveRoute(root, root_id).to_record()))
    replacement.chmod(0o600)
    os.replace(replacement, destination)
    return destination


def select_root_by_default_route(monkeypatch, parent: Path) -> Path:
    """Make this process choose its comms root from a home's route file, not AGENT_COMMS_ROOT.

    Returns the new home, under `parent`; `monkeypatch` restores the environment afterwards.
    """
    home = parent / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AGENT_COMMS_ROOT", raising=False)
    return home
