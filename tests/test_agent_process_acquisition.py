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
from toad.acp.wire_message import IncomingWireMessage, ReadAgentWireTask, WireInputFailure, WireResponse
from toad.render_processes import RenderProcessPool


def observed_wire_capture(function):
    """Run the actual declared acquisition; record its executing process."""
    return os.getpid(), function()


class ObservedWirePool(RenderProcessPool):
    def __init__(self):
        super().__init__()
        self.wire_pids = []

    async def run(self, function, *args):
        if isinstance(getattr(function, "__self__", None), ReadAgentWireTask):
            pid, result = await super().run(observed_wire_capture, function)
            self.wire_pids.append(pid)
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

        def profile(frame, event, arg):
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
                    started = time.perf_counter()
                    from textual.events import Key

                    # Measure driver delivery through paint. Pilot.press waits
                    # for whole-thread idleness twice per key, conflating input
                    # latency with concurrent response/preparation completion.
                    for key in "draft":
                        app._driver.send_message(Key(key, key))
                    async with asyncio.timeout(20):
                        while editor.text != "draft":
                            await asyncio.sleep(0)
                        painted = asyncio.Event()
                        editor.call_after_refresh(painted.set)
                        await painted.wait()
                    typing_ms = (time.perf_counter() - started) * 1000
                    await asyncio.wait_for(request, 20)
                    async with asyncio.timeout(20):
                        while "Original ACP active response" not in viewport_text(view.window):
                            await pilot.pause()
                    assert editor.text == "draft"
                    assert counts["ui_wire_json"] == counts["ui_wire_utf8"] == 0
                    assert counts["worker_wire_json"] == 0
                    assert len(pool.wire_pids) >= 4 and all(pid != os.getpid() for pid in pool.wire_pids)
                    recorded = [json.loads(line) for line in (tmp_path / "completion-wire.jsonl").read_text().splitlines()]
                    assert recorded == [{"prompt": original}]
                    assert app._exception is None
                    print({**counts, "process_wire_reads": len(pool.wire_pids),
                           "draft_ms": round(typing_ms, 1), "local_acp_requests": 1,
                           "provider_inputs": 0, "physical_terminal": False}, flush=True)
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
            threading.setprofile_all_threads(old_threads)
            sys.setprofile(old_ui)

    asyncio.run(mounted())
