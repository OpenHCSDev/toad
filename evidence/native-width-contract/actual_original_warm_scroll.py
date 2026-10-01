"""Join existing authenticated capture, SDK forks and physical warm-scroll owners.

No original attachment, input, provider request or public owner operation. This
uses the production CommsAgent directly: the existing test convenience factory
imports unrelated pytest/model fixtures, absent from the immutable runtime.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

WT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WT / "tests/tools"))
sys.path.insert(0, "/home/ts/wt/comms-turn-context-phase1-20261001/tools/cutover")
from original_owner_capture import CurrentTypedCapture
from record_installed_tui import ProcessOwner
from agent_comms.acp import CommsAgent
from agent_comms.child_process import ProcessIdentity
from agent_comms.comms import Comms
from agent_comms.field_codec import FieldCodec
from agent_comms.native_fork import ForkSessionHelper, ForkSessionRequest
from agent_comms.native_package import verify_native_package
from agent_comms.registration import Registration
from agent_comms.threads import Thread


def fingerprint(path):
    return {"bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


async def run(root, stage_proof, original_python):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    runtime = Path(sys.executable).parent
    stage = runtime.parent
    public = Path("/var/tmp/agent-comms-live-20260927-wzjtqhza")
    receipt = {"state": "PREPARING", "owner": "Heisenberg275", "fixture": str(root),
               "inputs": 0, "provider_requests": 0, "public_owner_operations": 0,
               "python": sys.executable, "runtime": str(stage),
               "original_python": str(original_python)}
    started = time.monotonic()
    owner = None
    processes = None
    captured = None
    try:
        verified = json.loads(stage_proof.read_text())
        activation = json.loads((stage / "activation.json").read_text())
        assert Path(verified["prefix"]).resolve() == Path(sys.prefix).resolve()
        assert Path(activation["stage"]).resolve() == Path(sys.prefix).resolve()
        assert verified["native_full_trust"] is True
        assert verified["package_count"] == 69
        assert all(item["byte_equal"] is True for item in verified["sources"])
        pins = {item["module"]: item["head"] for item in verified["sources"]}
        assert all(pins[module] == head for module, head in activation["pins"].items())
        native = Path(verified["native_package"])
        assert native == Path(activation["native_package"])
        receipt["pins"] = pins
        receipt["stage_proof"] = str(stage_proof)
        receipt["stage_proof_sha256"] = fingerprint(stage_proof)["sha256"]
        verify_native_package(native)
        captured = CurrentTypedCapture(public, original_python).read("nra-architecture")
        source = captured.require_current()
        original = Path(source.require_saved_session())
        receipt["original_process"] = FieldCodec.encode(source.require_process())
        receipt["original_file"] = str(original)
        receipt["original_before"] = fingerprint(original)
        environment = dict(captured.retained.environment)
        for key in tuple(environment):
            if key.startswith(("AGENT_COMMS_", "TOAD_VIDEO_")) or key in (
                    "PYTHONPATH", "DISPLAY", "NO_COLOR", "PI_PROMPT", "PI_PARENT_ID",
                    "PI_TASK", "PI_AGENT_ID"):
                environment.pop(key)
        fork_environment = dict(environment, PI_CODING_AGENT_DIR=str(root / "native-forks"))
        children = []
        for name in ("warm-a", "warm-b"):
            project = root / name
            project.mkdir(mode=0o700)
            identity = await ForkSessionHelper.run(
                ForkSessionRequest(str(native), str(original), str(project)),
                cwd=project, env=fork_environment)
            assert Path(identity.session_file).is_relative_to(root)
            captured.require_current()
            children.append(Thread(name, frozenset(), str(project),
                process_identity=ProcessIdentity.capture(os.getpid()),
                session_file=identity.session_file, model=source.model,
                thinking_level=source.thinking_level,
                task="Read-only acceptance. Do not resume inherited work or use tools."))
        service = Comms(root / "wire")
        root_id = service.messaging.initialize_private_initial_protocol()
        environment.update(AGENT_COMMS_ROOT=str(service.root),
            AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
            AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(native),
            AGENT_COMMS_RUNTIME_ROOT=str(runtime),
            AGENT_COMMS_ACP_LAUNCHER=str(runtime / "agent-comms-acp"),
            AGENT_COMMS_AGENT_BIN=str(runtime / "pi-comms-native"),
            PI_COMPACTION_TEST_PACKAGE=str(native),
            PI_CODING_AGENT_DIR=str(root / "native-forks"),
            PATH=str(runtime) + os.pathsep + environment.get("PATH", os.defpath),
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"))
        os.environ.clear()
        os.environ.update(environment)
        owner = CommsAgent(service, agent_bin=str(runtime / "pi-comms-native"),
            agent_args=list(captured.retained.arguments or ()), auto_wake=False,
            runtime_enabled=True, private_nk_native_package=native,
            private_nk_wire_root_id=root_id)
        for thread in children:
            service.registry.declare(thread)
        await owner._runtime.start()
        for thread in children:
            await owner.load_session(thread.worktree, thread.name)
            await owner.turns.prepare_selected_session(thread.name, thread)
        receipt["forks"] = [{"thread": thread.name, "session": thread.session_file,
                             "fingerprint": fingerprint(Path(thread.session_file))}
                            for thread in children]
        receipt["private_root_id"] = root_id
        captured.require_current()
        processes = ProcessOwner(Registration(service.root / "registry.json"))
        argv = [str(runtime / "python"), str(WT / "tests/tools/record_installed_tui.py"),
            "--owner", "Heisenberg275", "--journey", "warm_scroll", "--peer-thread", "warm-b",
            "--capture-state", "--profile", "--private-root", str(service.root),
            "--output", str(root / "physical01"), "--fit-window", "--width", "1280", "--height", "900",
            "--startup-wait", "10", "--max-duration", "120", "--finalize-seconds", "16",
            "--scroll-idle-seconds", "15", "--scroll-hold-seconds", "4", "--review-timing", "deferred",
            "--", str(runtime / "toad"), "acp", str(runtime / "python") + " -m agent_comms.acp",
            children[0].worktree, "--title", "Original saved warm history", "--session", children[0].name]
        receipt["recorder_argv"] = argv
        receipt["state"] = "ACTUAL_PHYSICAL_JOURNEY"
        with (root / "recorder.log").open("w") as log:
            child = processes.start(argv, env=environment, stdout=log, stderr=log)
            code = await asyncio.to_thread(child.process.wait, timeout=165)
        receipt["recorder_exit"] = code
        assert fingerprint(original) == receipt["original_before"]
        receipt["state"] = "SCOPED_PASS" if code == 0 else "FAILED_NO_REPLAY"
    except BaseException as error:
        receipt["state"] = "FAILED_NO_REPLAY"
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        try:
            if processes is not None:
                receipt["recorder_cleanup"] = processes.cleanup()
            if owner is not None:
                await owner.shutdown()
            if captured is not None:
                try:
                    current = captured.require_current()
                    receipt["original_after"] = fingerprint(Path(current.require_saved_session()))
                    receipt["original_process_after"] = FieldCodec.encode(current.require_process())
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                    # The acquisition witness ended before private launch. A
                    # later authorized cutover is an observation, not lost custody.
                    receipt["original_observation_after_error"] = f"{type(error).__name__}: {error}"
        finally:
            receipt["elapsed_seconds"] = time.monotonic() - started
            (root / "factory-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--stage-proof", required=True, type=Path)
    parser.add_argument("--original-python", required=True, type=Path,
                        help="Approved current producer interpreter for the original owner read")
    args = parser.parse_args()
    asyncio.run(run(args.root, args.stage_proof, args.original_python))
