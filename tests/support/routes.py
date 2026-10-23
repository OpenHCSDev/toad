"""The default comms route a test controls: private roots, and the file that selects one."""

from __future__ import annotations

import json
import os
from pathlib import Path
from support.roots import installed_wire
from agent_comms.threads import Thread


def private_root(path: Path, project: Path, message: str) -> Path:
    """A private bus at `path` holding `message` in #team from `peer`; returns `path`."""
    from agent_comms.thread_identity import UserThreadRole

    path.mkdir(mode=0o700)
    comms = installed_wire(path)
    comms.registry.declare(Thread("user", frozenset(), str(project), role=UserThreadRole))
    comms.registry.declare(Thread("owner", frozenset({"team"}), str(project / "owner-project")))
    comms.registry.declare(Thread("peer", frozenset({"team"}), str(project / "peer-project")))
    comms.messaging.send("peer", "#team", message)
    return path


def selecting_route(root: Path):
    """The default route that selects `root` and the bus it holds now."""
    from agent_comms.active_route import ActiveRoute
    from agent_comms.bus import Bus
    from agent_comms.recorded_bus import RecordedBusIdentity

    return ActiveRoute(root, RecordedBusIdentity.capture(Bus.path_in(root)))


def publish_route(home: Path, root: Path) -> Path:
    """Replace the default-route file under `home` so it selects `root`; returns the file."""
    directory = home / ".local/state/agent-comms"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    destination = directory / "active-route.json"
    replacement = directory / "replacement.json"
    replacement.write_text(json.dumps(selecting_route(root).to_record()))
    replacement.chmod(0o600)
    os.replace(replacement, destination)
    return destination


def route_home(monkeypatch, parent: Path) -> Path:
    """Isolate publication of the default used by a subsequent explicit launch."""
    home = parent / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("AGENT_COMMS_ROOT", raising=False)
    return home
