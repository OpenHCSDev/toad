"""The tailnet every test's processes see: fake tailscale and ssh first on PATH."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from agent_comms.transport.tailnet_buses import TailnetPeer

TAILSCALE = """\
import json, sys
peers = json.loads(open({state!r}).read())
print(json.dumps({{"Peer": {{peer["name"]: {{
    "HostName": peer["name"], "TailscaleIPs": [peer["address"]], "Online": True,
}} for peer in peers}}}}))
"""

SSH = """\
import json, sys, time
from pathlib import Path
held = Path({held!r})
deadline = time.monotonic() + 10
while held.exists() and time.monotonic() < deadline:
    time.sleep(0.05)
peers = {{peer["address"]: peer for peer in json.loads(open({state!r}).read())}}
peer = peers.get(sys.argv[-2])
if peer is None:
    sys.exit("ssh: connect to host " + sys.argv[-2] + ": No route to host")
print(json.dumps({{"threads": [{{}}] * peer["threads"]}}))
"""


@dataclass(frozen=True)
class FakeTailnet:
    """The tailnet discovery probes, wherever the probe runs.

    Every window asks the tailnet once when it opens (ClientApplication.discover_buses),
    and the ask is a Core read the observer process serves, so a stub in the test's own
    interpreter never reaches it, and the real tailscale and ssh would probe the owner's
    machines from every app test. Fake tailscale and ssh executables first on PATH are the
    boundary every process of the test shares: TailnetBuses runs for real against the peers
    a test holds here, and none by default.
    """

    directory: Path

    @classmethod
    def under(cls, attempt: Path) -> FakeTailnet:
        return cls(attempt / "tailnet")

    @property
    def state(self) -> Path:
        return self.directory / "peers.json"

    @property
    def held(self) -> Path:
        """While this file exists every probe waits, so a test can watch a slow peer."""
        return self.directory / "held"

    def install(self) -> None:
        self.directory.mkdir()
        self.state.write_text("[]")
        for name, source in (("tailscale", TAILSCALE), ("ssh", SSH)):
            program = self.directory / name
            program.write_text(f"#!{sys.executable}\n"
                               + source.format(state=str(self.state), held=str(self.held)))
            program.chmod(0o755)

    def path(self, inherited: str) -> str:
        """``inherited`` with these programs ahead of the real ones."""
        return f"{self.directory}:{inherited}"

    def hold(self, peer: TailnetPeer, threads: int) -> None:
        """``peer`` is on the tailnet and its CLI answers with ``threads`` threads."""
        peers = json.loads(self.state.read_text())
        peers.append({"name": peer.name, "address": peer.address, "threads": threads})
        self.state.write_text(json.dumps(peers))
