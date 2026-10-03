"""One cold saved-owner context disclosure in the original installed terminal.

The retained launch config stays in RAM. The existing SDK fork and private
protocol root are borrowed; no new fork, native input or priming RPC is made.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import shlex
import sys
import time


def load_recorder():
    recorder_path = Path(__file__).parent / "tools/record_installed_tui.py"
    spec = importlib.util.spec_from_file_location("cold_context_recorder", recorder_path)
    recorder = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = recorder
    spec.loader.exec_module(recorder)

    class ColdContextJourney(recorder.PhysicalJourney):
        scope = "Saved history/roster and cold native context Tree before any prompt"

        @classmethod
        def script(cls, args):
            mark = recorder.marker_command()
            helper = Path(__file__).resolve().parents[1] / "tools/performance/click_history.py"
            def click(state, target):
                return "exec --sync " + shlex.join((sys.executable, str(helper),
                    "--state", state, "--target", target))
            return "\n".join((
                mark + "saved --wait-history-seconds 12 --wait-history-thread configured-source",
                "key ctrl+b", "sleep 1", mark + "roster",
                click("phase-roster-state.pickle", "right_sidebar"),
                "sleep 7", mark + "context-open",
                click("phase-context-open-state.pickle", "context_tree"),
                "key Home Down Down space", "sleep 1", mark + "segment",
                "key Down", "sleep 1", mark + "provenance",
                "key Up", "sleep 1", mark + "segment-return", "",
            ))
    return recorder, recorder_path, ColdContextJourney


async def run(options):
    sys.dont_write_bytecode = True
    core = options.core_checkout.resolve()
    sys.path.append(str(core / "tools/cutover"))
    from agent_comms.child_process import ProcessIdentity
    from agent_comms.acp import CommsAgent
    from agent_comms.comms import Comms
    from agent_comms.field_codec import FieldCodec
    from agent_comms.input_disposition import InputDispositions
    from agent_comms.threads import Thread
    from original_owner_capture import CurrentTypedCapture
    recorder, recorder_path, ColdContextJourney = load_recorder()

    started = time.monotonic()
    base = options.output.resolve()
    assert base.is_relative_to(Path.home() / ".cache/agent-scratch")
    base.mkdir(parents=True, exist_ok=False)
    runtime = options.candidate_bin.resolve(strict=True)
    assert Path(sys.prefix).resolve() == runtime.parent
    activation = json.loads((runtime.parent / "activation.json").read_text())
    package = Path(activation["native_package"])
    root = options.fixture.resolve()
    service = Comms(root / "wire")
    previous = service.registry.require("configured-source")
    selected = Path(previous.require_saved_session())
    before = selected.read_bytes()
    assert not previous.require_process().alive(), "The previous owned controller must be retired"
    original = CurrentTypedCapture(options.public_root, options.original_python).read(
        "openhcs-audit-merged-runtime")
    source = original.require_current()
    public_file = Path(source.require_saved_session())
    public_before = hashlib.sha256(public_file.read_bytes()).hexdigest()
    assert source.model == previous.model and source.thinking_level == previous.thinking_level
    receipt = {"state": "PREPARING_COLD_CONFIGURED_OWNER", "fixture": str(root),
        "selected_file": str(selected), "selected_bytes": len(before),
        "selected_sha256_before": hashlib.sha256(before).hexdigest(),
        "public_file": str(public_file), "public_sha256_before": public_before,
        "model": source.model, "thinking": source.thinking_level.declared_name,
        "providers": 0, "native_inputs": 0, "priming_calls": 0,
        "python": sys.executable, "activation": str(runtime.parent / "activation.json")}
    owner = None
    try:
        environment = dict(original.retained.environment)
        with service.bus.log.locked():
            metadata = service.bus.log.read_metadata_unlocked()
        assert metadata.private, "Borrow only the already-owned private protocol root"
        root_id = metadata.root_id
        environment.update(AGENT_COMMS_ROOT=str(service.root),
            AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
            AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),
            PI_COMPACTION_TEST_PACKAGE=str(package),
            AGENT_COMMS_AGENT_BIN=str(runtime / "pi-comms-native"),
            AGENT_COMMS_RUNTIME_ROOT=str(runtime),
            PATH=str(runtime) + os.pathsep + environment.get("PATH", os.defpath),
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(base / "state"),
            XDG_DATA_HOME=str(base / "data"), TOAD_TEST_ATTEMPT="Einstein-cold595-physical01")
        for name in ("PYTHONPATH", "AGENT_COMMS_THREAD", "AGENT_COMMS_STARTUP_INPUT_KEY",
                     "PI_PROMPT", "PI_PARENT_ID", "PI_TASK", "PI_AGENT_ID", "NO_COLOR"):
            environment.pop(name, None)
        os.environ.clear()
        os.environ.update(environment)
        # Restore the declared stopped source through its original producer.
        # This publishes participant membership before any live attachment;
        # it is not a reader-side grant or a fabricated delivery receipt.
        service.threads.restore_stopped(service.registry.snapshot(), (previous.name,))
        owner = CommsAgent(service, private_nk_native_package=package,
            private_nk_wire_root_id=root_id, agent_bin=str(runtime / "pi-comms-native"),
            agent_args=list(original.retained.arguments or ()), auto_wake=False,
            runtime_enabled=True)
        declared = service.registry.declare(Thread("configured-source", previous.tags,
            previous.worktree, process_identity=ProcessIdentity.capture(os.getpid()),
            session_file=str(selected), model=source.model,
            thinking_level=source.thinking_level, task=previous.task))
        assert declared.created_at == previous.created_at
        await owner._runtime.start()
        await owner.load_session(declared.worktree, declared.name)
        assert declared.name not in owner.turns.persistent_backends
        assert not InputDispositions(service.root / InputDispositions.filename).read().rows
        receipt["controller"] = FieldCodec.encode(declared.require_process())
        receipt["state"] = "COLD_OWNER_STARTED_NO_NATIVE_ACQUISITION"
        (base / "terminal-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        command = [str(runtime / "toad"), "acp",
            shlex.join((str(runtime / "python"), "-m", "agent_comms.acp")),
            declared.worktree, "--title", "Cold configured saved context", "--session", declared.name]
        sys.argv = [str(recorder_path), "--output", str(base / "capture"),
            "--owner", "Einstein-cold595-physical01", "--private-root", str(service.root),
            "--journey", ColdContextJourney.declared_name, "--capture-state",
            "--review-timing", "deferred", "--fps", "20", "--width", "1500",
            "--height", "1100", "--fit-window", "--startup-wait", "10",
            "--max-duration", "65", "--tail-seconds", "2", "--", *command]
        (base / "caller.json").write_text(json.dumps(sys.argv, indent=2) + "\n")
        with (base / "recorder.log").open("w") as log:
            recording = await asyncio.create_subprocess_exec(sys.executable,
                str(Path(__file__).resolve()), "--record-only", *sys.argv[1:],
                stdout=log, stderr=asyncio.subprocess.STDOUT)
            assert await recording.wait() == 0, "Inspect original recorder log/receipt"
        persistent = owner.turns.persistent_backends[declared.name]
        child = persistent.custody.idle().child
        receipt["native_process"] = FieldCodec.encode(child.proc.identity)
        def phase(label):
            return pickle.loads((base / f"capture/phase-{label}-state.pickle").read_bytes())
        context = next(view for view in phase("provenance")["views"]
                       if view["mode"] == phase("provenance")["metadata"]["current_mode"])["context"]
        assert context["native_present"]
        assert context["detail"].startswith("Reference only; not read by browsing.")
        returned = next(view for view in phase("segment-return")["views"]
                        if view["mode"] == phase("segment-return")["metadata"]["current_mode"])["context"]
        assert len(returned["detail"]) > 100
        receipt["state"] = "SCOPED_COLD_TREE_TERMINAL_PASS_PENDING_PIXEL_REVIEW"
        receipt["context"] = context
        receipt["segment_text_characters"] = len(returned["detail"])
        from agent_comms.coordinator import Coordination
        from agent_comms.bus_publication import stable_thread_lookup
        with Coordination(str(service.root / "coordination.sqlite3")) as coordination:
            participant = coordination.participants.get(stable_thread_lookup(declared.created_at))
        assert participant.committed and participant.owner_thread == declared.name
        receipt["participant"] = FieldCodec.encode(participant)
        receipt["selected_sha256_after"] = hashlib.sha256(selected.read_bytes()).hexdigest()
        assert selected.read_bytes() == before
        assert hashlib.sha256(public_file.read_bytes()).hexdigest() == public_before
        original.require_current()
        assert not InputDispositions(service.root / InputDispositions.filename).read().rows
        receipt["original_source_unchanged"] = True
    except BaseException as error:
        receipt.update(state="FAILED_NO_REPLAY", error=repr(error))
        raise
    finally:
        if owner is not None:
            await owner.shutdown()
        if "child" in locals():
            receipt["native_child_retired"] = child.proc.retired and not child.proc.alive()
        receipt["elapsed_seconds"] = time.monotonic() - started
        (base / "terminal-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--record-only"]:
        sys.argv.pop(1)
        recorder, _, _ = load_recorder()
        recorder.main()
        raise SystemExit(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-bin", type=Path, required=True)
    parser.add_argument("--core-checkout", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--original-python", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
