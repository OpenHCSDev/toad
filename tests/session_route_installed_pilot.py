"""Actual modal export must refuse a changed default route before its sink."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms.active_route import ActiveRoute, publish_active_route
from agent_comms.comms import Comms
from textual.widgets import Input
from runtime_fixture import ToadApp
from toad.widgets.comms_transfer import WireExportDialog, WireExportRequest


async def main():
    saved_environment = os.environ.copy()
    try:
        with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"], prefix="route-ui-") as directory, \
             tempfile.TemporaryDirectory(dir="/var/tmp", prefix="route-private-") as private_directory:
            stage = Path(directory)
            isolated_home = stage / "home"
            isolated_home.mkdir(mode=0o700)
            os.environ.update(HOME=str(isolated_home), XDG_CONFIG_HOME=str(stage / "config"),
                              XDG_DATA_HOME=str(stage / "data"), XDG_STATE_HOME=str(stage / "state"))
            os.environ.pop("AGENT_COMMS_ROOT", None)
            old_root = isolated_home / ".agent-comms"
            Comms(old_root)
            app = ToadApp(project_dir=str(stage))
            async with app.run_test(size=(120, 38), notifications=True) as pilot:
                await pilot.pause()
                assert app.coordination_access.service.root == old_root
                app.transfers.open(WireExportRequest)
                await pilot.pause()
                dialog = app.screen
                assert isinstance(dialog, WireExportDialog)
                destination = stage / "must-not-export.jsonl"
                dialog.query_one("#export-path", Input).value = str(destination)
                private = Comms(Path(private_directory) / "wire")
                root_id = private.messaging.initialize_private_initial_protocol()
                package = Path(os.environ["AC_NATIVE_COPIED_PACKAGE"])
                publish_active_route(ActiveRoute(private.root, root_id, package))
                assert app.coordination_access.service.root == private.root
                assert await pilot.click(dialog.query_one("#submit-transfer"))
                await pilot.pause()
                await asyncio.gather(*(worker.wait() for worker in tuple(app.workers)
                                       if worker.group == WireExportRequest.declared_name))
                assert not destination.exists(), "Old dialog wrote after the actual default publication"
                async with asyncio.timeout(8):
                    while True:
                        frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                        if "route changed" in frame.lower():
                            break
                        await pilot.pause(.05)
                assert app._exception is None
        print("PASS_ACTUAL_INSTALLED_MODAL_DEFAULT_PUBLICATION_REFUSES_OLD_SINK", flush=True)
    finally:
        os.environ.clear()
        os.environ.update(saved_environment)


if __name__ == "__main__":
    asyncio.run(main())
