"""Textual-facing: SIGUSR1 ends a running app with its relaunch onto the root owner's runtime."""

import asyncio
import os
import signal

from agent_comms.launch_runtime import LaunchRuntime
from agent_comms.repo import Checkout
from agent_comms.root_runtime import RootRuntime, RootRuntimeStore

from toad.app import ToadApp
from toad.application_lifetime import Succeeded
from toad.session_scope import NoAgent


async def relaunched_onto(workspace, publish) -> Succeeded:
    app = ToadApp(agent_binding=NoAgent(), mode="store", project_dir=Checkout(workspace.project),
                  launch_root=workspace.launch_root)
    async with app.run_test(size=(140, 48)):
        publish(app.coordination_access.selection.root)
        os.kill(os.getpid(), signal.SIGUSR1)

        async def relaunched() -> None:
            while not isinstance(app.return_value, Succeeded):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(relaunched(), 30)
    return app.return_value


async def test_relaunch_stays_on_the_running_runtime_of_its_root(workspace):
    outcome = await relaunched_onto(workspace, lambda root: RootRuntime.publish(root, LaunchRuntime.running()))
    assert outcome == Succeeded(LaunchRuntime.running())


async def test_relaunch_moves_to_the_runtime_that_owns_its_root(workspace, tmp_path):
    owner = LaunchRuntime.at_prefix(tmp_path / "installed")

    def publish(root) -> None:
        RootRuntimeStore.at(root).retire_host(lambda process: True)
        RootRuntime.publish(root, owner)

    assert await relaunched_onto(workspace, publish) == Succeeded(owner)
