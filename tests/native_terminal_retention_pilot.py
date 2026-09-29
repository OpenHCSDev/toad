"""Installed ACP callback dispatch and real PTYs with a detached native session."""
import asyncio
from importlib.resources import files

from l0a_native_installed_pilot import main as native_fixture, until
from runtime_fixture import ToadApp
from toad.widgets.conversation import Conversation
from toad.widgets.terminal_tool import TerminalTool


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    mode = app.current_mode
    process, runner = agent.process.process, agent.process.runner
    owner = comms.registry.require("beta").process_identity
    request_id = 0

    async def rpc(method, **params):
        nonlocal request_id
        request_id += 1
        response = await agent.server.call({
            "jsonrpc": "2.0", "id": request_id, "method": method,
            "params": {"sessionId": agent.session_id, **params},
        })
        assert "error" not in response, response
        return response["result"]

    first = (await rpc("terminal/create", command="sh", args=[
        "-c", "sleep 1; printf 'ACTIVE_THEN_DETACHED\\n'"]))["terminalId"]
    execution = agent.controller.terminals.require(first)
    original_state = execution.state
    await app.new_session_screen(app.get_main_screen)
    assert agent.controller.surface.target is None
    assert not app.get_screen_stack(mode)[0].query(Conversation)
    second = (await rpc("terminal/create", command="sh", args=[
        "-c", "sleep .1; printf 'CREATED_WHILE_DETACHED\\n'"]))["terminalId"]
    assert (await rpc("terminal/wait_for_exit", terminalId=first))["exitCode"] == 0
    assert (await rpc("terminal/wait_for_exit", terminalId=second))["exitCode"] == 0
    assert "ACTIVE_THEN_DETACHED" in (await rpc("terminal/output", terminalId=first))["output"]
    assert "CREATED_WHILE_DETACHED" in (await rpc("terminal/output", terminalId=second))["output"]
    assert execution._view() is None
    assert agent.process.process is process and process.returncode is None
    assert agent.process.runner is runner and not runner.done()
    assert comms.registry.require("beta").process_identity == owner

    await app.switch_mode(mode)
    await until(pilot, lambda: len(app.screen.query(TerminalTool)) == 2)
    assert app.screen.conversation._shell is None, "ACP terminal resize spawned an unrelated shell"
    assert app.screen.query_one(f"#{first}", TerminalTool).state is original_state
    await until(pilot, lambda: "CREATED_WHILE_DETACHED" in "\n".join(
        strip.text for strip in app.screen._compositor.render_strips()))

    doomed = (await rpc("terminal/create", command="sh", args=["-c", "sleep 30"]))["terminalId"]
    await rpc("terminal/kill", terminalId=doomed)
    assert (await rpc("terminal/wait_for_exit", terminalId=doomed))["exitCode"] != 0
    await rpc("terminal/release", terminalId=second)
    try:
        agent.controller.terminals.output(second)
    except KeyError:
        pass
    else:
        raise AssertionError("Released ACP terminal remained addressable")
    await agent.controller.terminals.close()
    assert execution._command_task.done() and execution._process.returncode == 0
    assert not agent.controller.terminals.executions
    print("NATIVE_ACP_TERMINALS_RETAINED_AND_PAINTED", flush=True)


if __name__ == "__main__":
    asyncio.run(native_fixture(app_type=InstalledApp, acceptance=acceptance))
