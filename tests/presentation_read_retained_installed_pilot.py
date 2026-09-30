"""Extend the existing real retained SDK/ACP/UI read-only journey with closed bars.

The existing fixture owns forks, private wire, native/ACP launch, raw proof and
cleanup. This wrapper changes only real sidebar visibility and records custody.
It requires the canonical conversation driver's tests directory on PYTHONPATH.
"""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from agent_comms.registration import Registration
from agent_comms.field_codec import FieldCodec
from toad.widgets.side_bar import SideBar
import canonical_wire_retained_real_installed_pilot as retained


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class ClosedBarsWindow(retained.WindowApp):
    @asynccontextmanager
    async def run_test(self, **kwargs):
        async with super().run_test(**kwargs) as pilot:
            with self._context():
                self.workspace_chrome.channels.collapsed = True
                self.settings.sidebar.hide = True
                self.workspace_chrome.channels.roster.observation.set_enabled(False)
            try:
                yield pilot
            finally:
                with self._context():
                    assert self.workspace_chrome.channels.collapsed
                    assert self.screen.query_one("#thread-sidebar", SideBar).collapsed
                    assert not self.workspace_chrome.channels.roster.observation.enabled


async def main():
    assert os.environ["AC_REAL_READ_ONLY_CUSTODY"] == "1"
    assert not os.environ.get("AC_REAL_RETAINED_FIXTURE_ROOT")
    root = Path(os.environ["AC_REAL_SOURCE_ROOT"])
    original = Registration(root / "registry.json").snapshot().require_active(
        os.environ["AC_REAL_SOURCE_OWNER"])
    source = Path(original.session_file)
    before = {"source": str(source), "bytes": source.stat().st_size,
        "sha256": digest(source), "owner": FieldCodec.encode(original.process_identity)}
    evidence = Path(os.environ["L0A_EVIDENCE"])
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "original-source-before.json").write_text(json.dumps(before, indent=2))
    retained.WindowApp = ClosedBarsWindow
    await retained.main()
    current = Registration(root / "registry.json").snapshot().require_active(original.name)
    after = {"sha256": digest(source), "owner": FieldCodec.encode(current.process_identity)}
    with sqlite3.connect((evidence / "original-private-wire/coordination.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        native_inputs = db.execute("SELECT count(*) FROM native_runtime_input").fetchone()[0]
    receipt = {"source_unchanged": before["sha256"] == after["sha256"],
        "original_owner_unchanged": before["owner"] == after["owner"],
        "native_inputs": native_inputs, "both_bars_closed": True,
        "roster_projection_disabled": True, "after": after}
    (evidence / "closed-bars-custody.json").write_text(json.dumps(receipt, indent=2))
    assert receipt["source_unchanged"] and receipt["original_owner_unchanged"]
    assert native_inputs == 0
    print("CLOSED_BARS_RETAINED_READ_ONLY", json.dumps(receipt), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
