"""Original subprocess/SDK ingress leaves pure byte decoding off the App task."""

import asyncio
import json
import os
from pathlib import Path
import shlex
import sys
import threading
import time

from toad.acp.agent_process import AgentProcess
from toad.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.acp import wire_message
from toad.acp.wire_message import IncomingWireMessage, WireResponse
from toad.render_processes import RenderProcessPool

ReadAgentWireTask = getattr(wire_message, "ReadAgentWireTask", ())
WireInputFailure = getattr(wire_message, "WireInputFailure", ())


def observed_wire_capture(function):
    """Run the actual declared acquisition; record its executing process."""
    wall, cpu = time.perf_counter(), time.process_time()
    result = function()
    return os.getpid(), result, time.perf_counter() - wall, time.process_time() - cpu


class ObservedWirePool(RenderProcessPool):
    def __init__(self):
        super().__init__()
        self.wire_pids = []
        self.executions = []

    async def run(self, function, *args):
        from toad.acp.sdk_boundary import ValidateSessionUpdateTask

        task = getattr(function, "__self__", None)
        if isinstance(task, (ValidateSessionUpdateTask,)) or isinstance(task, ReadAgentWireTask):
            pid, result, wall, cpu = await super().run(observed_wire_capture, function)
            if isinstance(task, ReadAgentWireTask):
                self.wire_pids.append(pid)
            self.executions.append({"task": type(task).__name__, "pid": pid,
                                    "wall_ms": wall * 1000, "cpu_ms": cpu * 1000})
            return result
        return await super().run(function, *args)


def test_strict_wire_failures_keep_original_log_source_and_response_batches():
    bad_utf8 = IncomingWireMessage.read(b"\xff\n")
    assert isinstance(bad_utf8, WireInputFailure) and bad_utf8.source is None
    assert bad_utf8.message.startswith("[error] Unable to decode utf-8 from agent:")
    bad_json = IncomingWireMessage.read(b"{not json}\n")
    assert isinstance(bad_json, WireInputFailure) and bad_json.source == "{not json}\n"
    assert bad_json.message.startswith("[error] failed to decode JSON from agent:")
    bad_envelope = IncomingWireMessage.read(b"23\n")
    assert isinstance(bad_envelope, WireInputFailure) and bad_envelope.source == "23\n"
    assert bad_envelope.message == "[error] Agent sent an invalid JSON-RPC object or response batch"
    source = b'[{"jsonrpc":"2.0","id":1,"result":{}},{"jsonrpc":"2.0","id":2,"error":{"code":-1}}]\n'
    response = IncomingWireMessage.read(source)
    assert isinstance(response, WireResponse) and response.source == source.decode("utf-8")
    assert [item["id"] for item in response.payload] == [1, 2]


def test_original_sdk_stdio_decode_and_joined_app_input(tmp_path, monkeypatch):
    async def mounted():
        from agent_comms.comms import Comms
        from sidebar_retirement_pilot import viewport_text

        service = Comms(tmp_path / "wire")
        service.messaging.initialize_private_initial_protocol()
        for key in tuple(os.environ):
            if key.startswith("AGENT_COMMS_"):
                monkeypatch.delenv(key)
        for key, value in {"AGENT_COMMS_ROOT": service.root,
                           "XDG_CONFIG_HOME": tmp_path / "config",
                           "XDG_STATE_HOME": tmp_path / "state",
                           "XDG_DATA_HOME": tmp_path / "data"}.items():
            monkeypatch.setenv(key, str(value))
        peer = Path(__file__).with_name("acp_completion_server.py")
        definition = AgentDefinition.decode({
            "name": "Original local ACP ingress", "identity": "ingress", "short_name": "Ingress",
            "protocol": "acp", "run_command": {"*": shlex.join((sys.executable, str(peer)))},
        })
        ui_thread = threading.get_ident()
        counts = {"ui_wire_json": 0, "worker_wire_json": 0, "ui_wire_utf8": 0}
        loads_code = json.loads.__code__
        from toad.work_preparation import CopiedValue
        from toad.acp.agent import Agent
        from toad.jsonrpc import Server
        timing_codes = {loads_code: "json", CopiedValue.materialize.__code__: "result_copy",
                        Agent._log.__code__: "log_schedule", Server._dispatch_object_call.__code__: "rpc_dispatch"}
        timings, active = {}, {}

        def profile(frame, event, arg):
            code = frame.f_code
            key = (threading.get_ident(), id(frame))
            if code in timing_codes:
                if event == "call":
                    active[key] = time.thread_time()
                elif event == "return" and key in active:
                    name = timing_codes[code]
                    row = timings.setdefault(name, {"calls": 0, "cpu_ms": 0, "max_cpu_ms": 0})
                    elapsed = (time.thread_time() - active.pop(key)) * 1000
                    row["calls"] += 1
                    row["cpu_ms"] += elapsed
                    row["max_cpu_ms"] = max(row["max_cpu_ms"], elapsed)
            if event == "call" and frame.f_code is loads_code:
                source = frame.f_locals.get("s")
                if isinstance(source, str) and '"jsonrpc"' in source:
                    key = "ui_wire_json" if threading.get_ident() == ui_thread else "worker_wire_json"
                    counts[key] += 1
            elif (event == "c_call" and frame.f_code is AgentProcess.communicate.__code__
                  and getattr(arg, "__name__", None) == "decode"
                  and isinstance(getattr(arg, "__self__", None), bytes)):
                counts["ui_wire_utf8"] += 1

        pool = ObservedWirePool()
        app = ToadApp(project_dir=str(tmp_path), agent_data=definition, renderer=pool)
        old_ui, old_threads = sys.getprofile(), threading.getprofile()
        old_trace = sys.gettrace()
        threading.setprofile_all_threads(profile)
        try:
            async with app.run_test(size=(110, 35)) as pilot:
                view = app.selected_session.conversation
                async with asyncio.timeout(20):
                    while view.agent is None:
                        await pilot.pause()
                    agent = view.agent
                    await agent.session.settled.wait()
                assert agent.session.connected
                child = agent.process.process
                pid = child.pid
                original = "Original ACP active response 界\n" * 512
                request = asyncio.create_task(agent.send_prompt(original))
                try:
                    editor = view.prompt.prompt_text_area
                    editor.focus(scroll_visible=False)
                    from textual.events import Key

                    # Both versions start at the same original raw stdout read,
                    # before UTF8/JSON acquisition. Enqueue native driver input
                    # there, so UI decoding cannot run before the clock starts.
                    started = None
                    stream_arrived = asyncio.Event()
                    def trace(frame, event, arg):
                        nonlocal started
                        if frame.f_code is not AgentProcess.communicate.__code__:
                            return None
                        if event == "line" and started is None:
                            line = frame.f_locals.get("line")
                            if isinstance(line, bytes) and b"agent_message_chunk" in line:
                                started = time.perf_counter()
                                for key in "draft":
                                    app._driver.send_message(Key(key, key))
                                stream_arrived.set()
                        return trace
                    sys.settrace(trace)
                    async with asyncio.timeout(20):
                        await stream_arrived.wait()
                        while editor.text != "draft":
                            await asyncio.sleep(0)
                        painted = asyncio.Event()
                        editor.call_after_refresh(painted.set)
                        await painted.wait()
                    typing_ms = (time.perf_counter() - started) * 1000
                    sys.settrace(old_trace)
                    await asyncio.wait_for(request, 20)
                    async with asyncio.timeout(20):
                        while "Original ACP active response" not in viewport_text(view.window):
                            await pilot.pause()
                    assert editor.text == "draft"
                    if ReadAgentWireTask:
                        assert counts["ui_wire_json"] == counts["ui_wire_utf8"] == 0
                        assert counts["worker_wire_json"] == 0
                        assert len(pool.wire_pids) >= 4 and all(pid != os.getpid() for pid in pool.wire_pids)
                    else:
                        assert counts["ui_wire_json"] >= 4 and not pool.wire_pids
                    recorded = [json.loads(line) for line in (tmp_path / "completion-wire.jsonl").read_text().splitlines()]
                    assert recorded == [{"prompt": original}]
                    assert app._exception is None
                    result = {**counts, "process_wire_reads": len(pool.wire_pids),
                           "draft_ms": round(typing_ms, 1), "local_acp_requests": 1,
                           "provider_inputs": 0, "physical_terminal": False,
                           "cpu_scopes_overlap": True, "timings": timings,
                           "worker_executions": pool.executions}
                    (tmp_path / "wire-comparison.json").write_text(json.dumps(result, indent=2) + "\n")
                    print(result, flush=True)
                finally:
                    if not request.done():
                        request.cancel()
                    await asyncio.gather(request, return_exceptions=True)
                    await agent.stop()
                assert not Path(f"/proc/{pid}").exists()
                assert not any(task.get_name() == "agent-wire-read"
                               for task in asyncio.all_tasks() if not task.done())
            assert all(not Path(f"/proc/{pid}").exists() for pid in pool.wire_pids)
        finally:
            sys.settrace(old_trace)
            threading.setprofile_all_threads(old_threads)
            sys.setprofile(old_ui)

    asyncio.run(mounted())
