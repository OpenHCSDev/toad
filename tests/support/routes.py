"""The default comms route a test controls: private roots, and the file that selects one."""

from __future__ import annotations

import json
import os
from pathlib import Path


def private_root(path: Path, project: Path, message: str) -> tuple[Path, str]:
    """A private wire at `path` holding `message` in #team from `peer`; returns it and its root id."""
    from agent_comms.comms import Comms
    from agent_comms.thread_identity import ThreadRole
    from agent_comms.threads import Thread

    path.mkdir(mode=0o700)
    comms = Comms(path, private_initial_writes=True)
    comms.registry.declare(Thread("user", frozenset(), str(project), role=ThreadRole.USER))
    comms.registry.declare(Thread("owner", frozenset({"team"}), str(project / "owner-project")))
    comms.registry.declare(Thread("peer", frozenset({"team"}), str(project / "peer-project")))
    root_id = comms.messaging.initialize_private_initial_protocol()
    comms.messaging.send_initial_cohort("peer", "#team", message)
    return path, root_id


def publish_route(home: Path, root: Path, root_id: str) -> Path:
    """Replace the default-route file under `home` so it selects `root`; returns the file."""
    directory = home / ".local/state/agent-comms"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    destination = directory / "active-route.json"
    replacement = directory / "replacement.json"
    replacement.write_text(json.dumps({"version": 1, "root": str(root), "wire_root_id": root_id,
                                       "native_package": str(home / "unused-package")}))
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
