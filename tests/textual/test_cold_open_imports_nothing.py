"""Opening a cold channel imports no Core module: one-time discovery happened at startup, not under input."""

import sys


async def test_a_cold_channel_open_imports_no_core_module(workspace):
    me = workspace.project.name
    workspace.thread(me, "fixture", running=True)
    workspace.comms.channels.create_tag("cold")
    workspace.comms.messaging.send(me, "#cold", "cold marker")

    async with workspace.app(size=(120, 40)) as ui:
        owner = ui.selected_tab
        before = set(sys.modules)
        await ui.open_channel("#cold", actor=me)
        await ui.until_shows("cold marker")
        imported = sorted(name for name in set(sys.modules) - before if name.startswith("agent_comms"))
        assert not imported, imported
        await ui.select_tab(owner)
