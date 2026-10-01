"""Installed ACP callback dispatch and real PTYs with a detached native session."""
import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
import signal
import sys

from agent_comms.child_process import ProcessIdentity

from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import conversation_paint
from runtime_fixture import ToadApp
from saved_state_user_journey_pilot import click_tab
from toad.widgets.terminal_tool import TerminalTool


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


def pty_masters():
    """Observe this real application's PTY resources, not its private fields."""
    descriptors = set()
    for descriptor in Path("/proc/self/fd").iterdir():
        try:
            target = descriptor.readlink()
        except FileNotFoundError:
            continue  # A real descriptor can retire during observation.
        if str(target) == "/dev/pts/ptmx":
            descriptors.add(int(descriptor.name))
    return descriptors


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    mode = app.selected_session.id
    process, runner = agent.process.process, agent.process.runner
    owner = comms.registry.require("beta").process_identity
    request_id = 0
    terminals = agent.controller.terminals
    initial_pty_masters = pty_masters()
    evidence = Path(os.environ["L0A_EVIDENCE"])

    async def request(method, **params):
        nonlocal request_id
        request_id += 1
        return await agent.server.call({
            "jsonrpc": "2.0", "id": request_id, "method": method,
            "params": {"sessionId": agent.session_id, **params},
        })

    async def rpc(method, **params):
        response = await request(method, **params)
        assert "error" not in response, response
        return response["result"]

    first = (await rpc("terminal/create", command="sh", args=[
        "-c", "sleep 1; printf 'ACTIVE_THEN_DETACHED\\n'"]))["terminalId"]
    execution = terminals.require(first)
    original_state = execution.state
    original_custody = await execution.custody()
    await app.session_navigation.new(app.session_navigation.default_source)
    assert agent.controller.surface.target is None
    second = (await rpc("terminal/create", command="sh", args=[
        "-c", "sleep .1; printf 'CREATED_WHILE_DETACHED\\n'"]))["terminalId"]
    assert (await rpc("terminal/wait_for_exit", terminalId=first))["exitCode"] == 0
    assert (await rpc("terminal/wait_for_exit", terminalId=second))["exitCode"] == 0
    assert "ACTIVE_THEN_DETACHED" in (await rpc("terminal/output", terminalId=first))["output"]
    assert "CREATED_WHILE_DETACHED" in (await rpc("terminal/output", terminalId=second))["output"]
    assert execution.outcome.finished and execution.outcome.successful
    assert original_custody.process.returncode == 0 and original_custody.master.closed
    assert agent.process.process is process and process.returncode is None
    assert agent.process.runner is runner and not runner.done()
    assert comms.registry.require("beta").process_identity == owner

    await click_tab(app, pilot, mode)
    await until(pilot, lambda: len(app.screen.query(TerminalTool)) == 2)
    assert agent.controller.surface.target is app.selected_session.conversation
    assert app.screen.query_one(f"#{first}", TerminalTool).state is original_state
    assert await execution.custody() is original_custody
    await until(pilot, lambda: "CREATED_WHILE_DETACHED" in conversation_paint(app.screen))
    app.save_screenshot("terminal-reattached.svg", path=str(evidence))
    assert pty_masters() == initial_pty_masters

    # A cancelled wait is an observer cancellation, not a second process owner.
    doomed = (await rpc("terminal/create", command="sleep", args=["30"]))["terminalId"]
    running = terminals.require(doomed)
    running_custody = await running.custody()
    child = ProcessIdentity.capture(running_custody.process.pid)
    assert child.alive() and not running.outcome.finished
    waiter = asyncio.create_task(rpc("terminal/wait_for_exit", terminalId=doomed))
    try:
        await pilot.pause()
        assert not waiter.done()
        waiter.cancel()
        cancellation, = await asyncio.gather(waiter, return_exceptions=True)
        assert isinstance(cancellation, asyncio.CancelledError)
        assert child.alive() and not running.outcome.finished
        assert await running.custody() is running_custody
    finally:
        if not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
    await rpc("terminal/kill", terminalId=doomed)
    killed = await rpc("terminal/wait_for_exit", terminalId=doomed)
    assert killed["signal"] == signal.Signals(signal.SIGKILL).name
    assert (await rpc("terminal/output", terminalId=doomed))["exitStatus"] == killed
    assert running.outcome.finished and not running.outcome.successful
    assert not child.alive() and running_custody.master.closed
    assert running_custody.process.returncode == -signal.SIGKILL

    # A byte bound may cut through a UTF-8 scalar, including its entire tail.
    bounded = (await rpc("terminal/create", command=sys.executable, args=[
        "-c", "import sys; sys.stdout.buffer.write('😀'.encode('utf-8'))"
    ], outputByteLimit=2))["terminalId"]
    assert (await rpc("terminal/wait_for_exit", terminalId=bounded))["exitCode"] == 0
    bounded_output = await rpc("terminal/output", terminalId=bounded)
    assert bounded_output["truncated"] is True
    assert bounded_output["output"] == ""
    assert len(bounded_output["output"].encode("utf-8")) <= 2
    assert "😀" in "\n".join(line.content.plain for line in
                              terminals.require(bounded).state.buffer.lines)

    # A missing cwd is a real spawn failure; an unknown command merely exits.
    before_failed_create = frozenset(terminals.executions)
    before_failed_pty = pty_masters()
    absent = Path(app.project_dir) / "terminal-startup-directory-that-does-not-exist"
    assert not absent.exists()
    failure = await request("terminal/create", command="sh", args=["-c", "printf unused"],
                            cwd=str(absent))
    assert "error" in failure, failure
    assert frozenset(terminals.executions) == before_failed_create
    assert pty_masters() == before_failed_pty

    await rpc("terminal/release", terminalId=second)
    assert second not in terminals.executions
    assert "error" in await request("terminal/output", terminalId=second)

    released = (await rpc("terminal/create", command="sleep", args=["30"]))["terminalId"]
    released_custody = await terminals.require(released).custody()
    released_child = ProcessIdentity.capture(released_custody.process.pid)
    assert released_child.alive()
    await rpc("terminal/release", terminalId=released)
    assert released not in terminals.executions and not released_child.alive()
    assert released_custody.master.closed
    assert "error" in await request("terminal/output", terminalId=released)

    # Cancellation belongs to the request; original retirement still joins.
    interrupted = (await rpc("terminal/create", command="sleep", args=["30"]))["terminalId"]
    interrupted_execution = terminals.require(interrupted)
    interrupted_custody = await interrupted_execution.custody()
    interrupted_child = ProcessIdentity.capture(interrupted_custody.process.pid)
    releasing = asyncio.create_task(rpc("terminal/release", terminalId=interrupted))
    await asyncio.sleep(0)  # Enter the real handler, without a screen barrier.
    assert terminals.require(interrupted) is interrupted_execution
    assert releasing.cancel(), "Release settled before the cancellation observation"
    await asyncio.sleep(0)  # Deliver the first cancellation at its original await.
    assert releasing.cancel(), "Repeated cancellation was not exercised"
    release_cancellation, = await asyncio.gather(releasing, return_exceptions=True)
    assert isinstance(release_cancellation, asyncio.CancelledError)
    assert releasing.cancelling() == 2
    assert interrupted not in terminals.executions
    assert interrupted_execution.outcome.finished
    assert interrupted_custody.master.closed and not interrupted_child.alive()
    assert "error" in await request("terminal/output", terminalId=interrupted)

    # Original creation publishes its execution before yielding to PTY spawn.
    # Cancel at that real await, preserving whichever acquisition actually won.
    before_startup = frozenset(terminals.executions)
    before_startup_pty = pty_masters()
    starting = asyncio.create_task(rpc("terminal/create", command="sleep", args=["30"]))
    await asyncio.sleep(0)
    startup_ids = frozenset(terminals.executions) - before_startup
    assert len(startup_ids) == 1 and not starting.done(), "Startup phase was not observed"
    startup_id, = startup_ids
    startup_execution = terminals.require(startup_id)
    acquisition = asyncio.create_task(startup_execution.custody())
    assert starting.cancel()
    startup_cancellation, = await asyncio.gather(starting, return_exceptions=True)
    assert isinstance(startup_cancellation, asyncio.CancelledError)
    try:
        acquired = await acquisition
    except asyncio.CancelledError:
        startup_observation = {"acquisition": "refused_before_custody"}
    else:
        assert acquired.master.closed and acquired.process.returncode is not None
        startup_observation = {
            "acquisition": "original_custody_joined", "pid": acquired.process.pid,
            "return_code": acquired.process.returncode, "pty_closed": acquired.master.closed,
        }
    assert startup_id not in terminals.executions and startup_execution.outcome.finished
    assert frozenset(terminals.executions) == before_startup
    assert pty_masters() == before_startup_pty

    await terminals.close()
    assert execution.outcome.finished and execution.outcome.successful
    assert not terminals.executions and pty_masters() == initial_pty_masters
    assert not requests, "Terminal-only acceptance made a model request"
    assert comms.registry.require("beta").process_identity == owner and owner.alive()
    (evidence / "terminal-lifecycle-acceptance.json").write_text(json.dumps({
        "normal_exit": {"exitCode": 0}, "signal_exit": killed,
        "cancelled_wait_preserves_original_process": True,
        "bounded_utf8": bounded_output,
        "failed_startup": failure,
        "released_child": {"pid": released_child.pid, "alive": released_child.alive(),
                           "pty_closed": released_custody.master.closed},
        "cancelled_release": {"cancellations": releasing.cancelling(),
                              "pid": interrupted_child.pid, "alive": interrupted_child.alive(),
                              "pty_closed": interrupted_custody.master.closed,
                              "address_present": interrupted in terminals.executions},
        "cancelled_startup": startup_observation,
        "controller_addresses_after_close": len(terminals.executions),
        "pty_masters_before": sorted(initial_pty_masters),
        "pty_masters_after": sorted(pty_masters()),
        "provider_requests": len(requests),
        "native_owner_preserved": True,
    }, indent=2) + "\n")
    print("NATIVE_ACP_TERMINALS_RETAINED_AND_PAINTED", flush=True)


if __name__ == "__main__":
    asyncio.run(native_fixture(
        app_type=InstalledApp, acceptance=acceptance, headless=False,
        provider_request_budget=0,
        fixture_stage=Path(os.environ["TOAD_TERMINAL_FIXTURE_ROOT"]),
    ))
