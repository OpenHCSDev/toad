"""A conservative legacy read-marker reset is visible to the human."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms.threads import Thread
from agent_comms.comms import wire
from runtime_fixture import ToadApp
from toad.widgets.comms_sidebar import CommsSidebar


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-marker-notice-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
        )
        comms = wire(root / "wire")
        comms.threads.register(Thread("sender", frozenset({"team"}), str(root)))
        viewer = comms.messaging.user_identity(str(root)).name
        message = comms.messaging.send_message("sender", "#team", "unproved prior read")
        marker = comms.root / "read_markers.json"
        marker.write_text(
            json.dumps({comms.bus._marker_key(viewer, "#team"): message.seq})
        )
        # Simulate a pre-ledger root. Fixture setup itself opens a new ledger;
        # a later legacy-marker write is deliberately not a second migration.
        comms.bus.reads.path.unlink()
        comms = wire(root / "wire")

        notices = []
        with patch.object(CommsSidebar, "notify", autospec=True) as notify:
            notify.side_effect = lambda _sidebar, text, **kwargs: notices.append(
                (text, kwargs)
            )
            app = ToadApp(project_dir=str(root))
            async with app.run_test(size=(120, 40)) as pilot:
                sidebar = app.screen.query_one(CommsSidebar)
                await sidebar._read_snapshot(comms.views.revision())
                await pilot.pause()
                assert comms.views.viewer_snapshot(str(root)).channel_unread["#team"] == 1
                assert len(notices) == 1
                assert "reset" in notices[0][0]
                assert notices[0][1]["severity"] == "warning"
                await sidebar._read_snapshot(comms.views.revision())
                assert len(notices) == 1
            await asyncio.get_running_loop().shutdown_default_executor()
    print("Legacy channel read marker reset produced one visible warning")


if __name__ == "__main__":
    asyncio.run(main())
