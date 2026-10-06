"""UNISSUED476 template: original BoundedRun custody, no runtime authority."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

grant = Path("UNBOUND_476_ACTUAL_ISSUED_GRANT_PATH")
lifecycle = Path("UNBOUND_476_ACTUAL_LIFECYCLE_PATH")
grant_sha256 = "UNBOUND_476_ACTUAL_ISSUED_GRANT_SHA256"

async def drain(reader, path):
    with path.open("xb") as target:
        while data := await reader.read(65536):
            target.write(data)
            target.flush()

async def main():
    raw = grant.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == grant_sha256
    g = json.loads(raw)
    lr = lifecycle.read_bytes()
    l = json.loads(lr)
    assert l["execution_authorized"] and l["native_EXEC_authorized"] and l["native_READ_authorized"]
    assert l["control_attempts_consumed"] == 0
    assert not l["source_publicdecoder_READ_authorized"]
    assert l["environment"] == g["environment"]
    control = g["exact_control"]
    command = tuple(g["outer_argv"])
    assert command == (command[0], "-B", control["path"], "--warm-admission-only")
    assert Path(sys.executable) == Path(command[0])
    assert hashlib.sha256(Path(control["path"]).read_bytes()).hexdigest() == control["sha256"]
    for path, expected in g["control_hashes"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
    out = Path(__file__).parent
    binding_proofs = json.loads((out / "App-proof-binding.json").read_bytes())
    for name, expected in binding_proofs.items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == expected
    evidence = Path(g["environment"]["set"]["L0A_EVIDENCE"])
    assert not evidence.exists()
    evidence.mkdir(mode=0o700, parents=True)
    Path(g["environment"]["set"]["TMPDIR"]).mkdir(mode=0o700)
    environment = os.environ.copy()
    for key in g["environment"]["unset"]:
        environment.pop(key, None)
    environment.update(g["environment"]["set"])
    from agent_comms.child_process import BoundedRun, ProcessIdentity
    from agent_comms.field_codec import FieldCodec
    controller = FieldCodec.encode(ProcessIdentity.capture(os.getpid()))
    binding = {"issued": str(grant), "issued_sha256": hashlib.sha256(raw).hexdigest(),
               "lifecycle": str(lifecycle), "lifecycle_sha256_at_launch": hashlib.sha256(lr).hexdigest(),
               "controller": controller, "argv": command, "cwd": g["cwd"],
               "environment": g["environment"], "timeout": g["control_timeout_seconds"],
               "owner": "Original BoundedRun.session/AttachedChild; two authored localhost inputs, no public decoder"}
    (out / "warm-effective-release.json").write_bytes(lr)
    with (out / "warm-command.json").open("x") as stream:
        json.dump(binding, stream, indent=2)
    start = time.monotonic()
    child = None
    tasks = []
    timed_out = False
    error = None
    outcome = None
    try:
        async with BoundedRun.session(command, timeout=g["control_timeout_seconds"],
                                      cwd=g["cwd"], env=environment) as child:
            handle = {"controller": controller, "child": FieldCodec.encode(child.identity),
                      "argv": command, "cwd": g["cwd"]}
            with (out / "warm-handle.json").open("x") as stream:
                json.dump(handle, stream, indent=2)
            print("WARM_HANDLE", json.dumps(handle), flush=True)
            tasks = [asyncio.create_task(drain(child.stdout, out / "warm.stdout.log")),
                     asyncio.create_task(drain(child.stderr, out / "warm.stderr.log"))]
            outcome = await child.wait()
    except TimeoutError:
        timed_out = True
    except BaseException as failure:
        error = repr(failure)
    finally:
        drained = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
        drain_errors = [repr(item) for item in drained if isinstance(item, BaseException)]
        terminal = {"elapsed": time.monotonic() - start,
                    "returncode": None if child is None else child.returncode,
                    "timed_out": timed_out, "error": error, "drain_errors": drain_errors,
                    "outcome": None if outcome is None else FieldCodec.encode(outcome),
                    "child_retired": None if child is None else child.retired,
                    "owned_group_members": [] if child is None else FieldCodec.encode(child.platform.group_members(child.identity)),
                    "controller": controller, "child": None if child is None else FieldCodec.encode(child.identity),
                    "grant": str(grant),
                    "input_and_qualification_claim": "Original mounted receipt must prove both verified branches and exactly2inputs; no effect absence or whole qualification inferred from launch/exit alone"}
        with (out / "warm-terminal.json").open("x") as stream:
            json.dump(terminal, stream, indent=2)
        print("WARM_TERMINAL", json.dumps(terminal), flush=True)
        await asyncio.get_running_loop().shutdown_default_executor()
        return 124 if timed_out else 1 if error or drain_errors or child is None or child.returncode is None else child.returncode

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
