"""Textual-facing: a launch with no local agent (a remote --comms-profile launch) opens the Comms home.

Toad's upstream agent store was a second home beside the workspace's welcome view, chosen by
the agent binding; a remote launch has no local agent and landed in it. The fork has one home.
"""

import asyncio

from agent_comms.repo import Checkout

from toad.app import ToadApp
from toad.comms_root import LocalCoreConnection
from toad.constants import WELCOME
from toad.agent_origin import NoAgent


async def test_an_agentless_launch_opens_the_welcome_workspace(workspace):
    app = ToadApp(agent_binding=NoAgent(), project_dir=Checkout(workspace.project),
                  connection=LocalCoreConnection.from_launch(workspace.launch_root))
    async with app.run_test(size=(140, 48)) as pilot:
        async with asyncio.timeout(30):
            while app.selected_mode != WELCOME:
                await pilot.pause(0.05)
        assert app.current_mode == "workspace"
        assert app.tab_order.home == WELCOME
        assert set(app.MODES) == {"workspace"}
