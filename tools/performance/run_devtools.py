"""Run the official Textual dev console on loopback beside a diagnostic fixture."""

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--name", default="toad-devtools-" + time.strftime("%Y%m%d-%H%M%S"))
parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
parser.add_argument("--framework", type=Path, required=True)
parser.add_argument("--environment", type=Path, required=True)
parser.add_argument("--tools-environment", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, default=Path.home() / ".cache/toad-performance")
parser.add_argument("--dependency-path", type=Path, action="append", default=[])
parser.add_argument("--display", default=":98")
parser.add_argument("--privileged-display", action="store_true")
args = parser.parse_args()
args.output_dir.mkdir(parents=True, exist_ok=True)
base = args.output_dir.resolve() / args.name
tools = args.tools_environment.resolve()
source, framework = str(args.source.resolve()), str(args.framework.resolve())
tool_packages = subprocess.check_output([str(tools / "bin/python"), "-c",
    "import os,site; print(os.pathsep.join(site.getsitepackages()))"], text=True).strip()
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
server_env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=framework + "/src", COLUMNS="180")
server_code = (
    "from aiohttp.web import run_app; "
    "from textual_dev.server import _make_devtools_aiohttp_app; "
    f"run_app(_make_devtools_aiohttp_app(port={port}), host='127.0.0.1', port={port}, print=None)"
)
with Path(str(base) + "-console.log").open("w") as console_log:
    console = subprocess.Popen([str(tools / "bin/python"), "-u", "-c", server_code],
                               env=server_env, stdout=console_log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 10
        while True:
            assert console.poll() is None, "Textual console failed to start"
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.2):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Textual console did not become ready")
                time.sleep(.1)
        env = dict(os.environ, TEXTUAL="devtools,debug", TEXTUAL_DEVTOOLS_PORT=str(port),
                   TEXTUAL_DEVTOOLS_HOST="127.0.0.1", TEXTUAL_SLOW_THRESHOLD="100",
                   TOAD_VALIDATION_EXTRA_PYTHONPATH=os.pathsep.join([*(str(path.resolve()) for path in args.dependency_path), tool_packages]),
                   TOAD_VALIDATION_ASYNCIO_LOG=str(base) + "-asyncio.log",
                   TOAD_REVISIT_SIDEBAR="1")
        subprocess.run([
            sys.executable, str(Path(__file__).with_name("run_isolated.py")), "--source", source,
            "--framework", framework, "--environment", str(args.environment.resolve()),
            "--name", base.name, "--output-dir", str(args.output_dir.resolve()), "--display", args.display,
            *(["--privileged-display"] if args.privileged_display else []), "--fixture", "--open-only",
        ], env=env, check=True, timeout=320)
        state = json.loads(Path(str(base) + "-state.json").read_text())
        assert state["diagnostics"]["devtools_connected"]
        assert state["diagnostics"]["asyncio_debug"]
        assert state["diagnostics"]["slow_callback_ms"] == 50
        print({"console_pid": console.pid, "port": port, "diagnostics": state["diagnostics"],
               "console_log": str(base) + "-console.log", "asyncio_log": str(base) + "-asyncio.log"})
    finally:
        if console.poll() is None:
            console.send_signal(signal.SIGINT)
            try:
                console.wait(timeout=10)
            except subprocess.TimeoutExpired:
                console.terminate()
                console.wait(timeout=5)
