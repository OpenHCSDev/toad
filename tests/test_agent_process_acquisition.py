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

        app = ToadApp(project_dir=str(tmp_path), agent_data=definition)
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
                    await pilot.press("d", "r", "a", "f", "t")
                    typing_ms = (time.perf_counter() - started) * 1000
                    await asyncio.wait_for(request, 20)
                    async with asyncio.timeout(20):
                        while "Original ACP active response" not in viewport_text(view.window):
                            await pilot.pause()
                    assert editor.text == "draft"
                    assert counts["ui_wire_json"] == counts["ui_wire_utf8"] == 0
                    assert counts["worker_wire_json"] >= 4
                    recorded = [json.loads(line) for line in (tmp_path / "completion-wire.jsonl").read_text().splitlines()]
                    assert recorded == [{"prompt": original}]
                    assert app._exception is None
                    print({**counts, "draft_ms": round(typing_ms, 1), "local_acp_requests": 1,
                           "provider_inputs": 0, "physical_terminal": False}, flush=True)
                finally:
                    if not request.done():
                        request.cancel()
                    await asyncio.gather(request, return_exceptions=True)
                    await agent.stop()
                assert not Path(f"/proc/{pid}").exists()
                assert not any(task.get_name() in ("agent-utf8", "agent-json")
                               for task in asyncio.all_tasks() if not task.done())
        finally:
            threading.setprofile_all_threads(old_threads)
            sys.setprofile(old_ui)

    asyncio.run(mounted())
