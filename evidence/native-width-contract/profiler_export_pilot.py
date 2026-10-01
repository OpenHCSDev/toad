"""Exercise actual py-spy export while its separately owned target stays alive."""
from pathlib import Path
import json
import os
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests/tools"))
from record_installed_tui import ProcessOwner, ProfileProcess


def launch(output):
    owner = ProcessOwner()
    target = owner.start([sys.executable, "-c",
                          "import time\nend = time.monotonic() + 60\n"
                          "while time.monotonic() < end: sum(range(10000))"])
    (output / "target.json").write_text(json.dumps({
        "pid": target.child.identity.pid, "start_ticks": target.child.identity.start_time,
    }))
    argv = [shutil.which("py-spy"), "record", "--pid", str(target.child.identity.pid),
            "--format", "chrometrace", "--duration", "30", "--rate", "25",
            "--output", str(output / "cpu-profile.json")]
    os.execv(argv[0], argv)


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    owner = ProcessOwner()
    receipt = {"scope": "Actual sampling-process lifetime; no UI, ACP, inputs or provider"}
    try:
        with (output / "profiler.log").open("w") as log:
            profile = owner.start([sys.executable, __file__, "--launch", str(output)],
                                  process_type=ProfileProcess, stdout=log, stderr=log)
            deadline = time.monotonic() + 8
            while "Sampling process" not in (output / "profiler.log").read_text():
                if time.monotonic() >= deadline or profile.process.poll() is not None:
                    raise RuntimeError("Actual profiler did not start")
                time.sleep(.05)
            identity = json.loads((output / "target.json").read_text())
            target = owner.transfer(identity["pid"], identity["start_ticks"])
            time.sleep(.5)
            try:
                raise TimeoutError("Representative interrupted capture")
            except TimeoutError as error:
                receipt["interruption"] = str(error)
            finally:
                profile.export(output, receipt)
            receipt["target_alive_after_export"] = target.child.identity.alive()
            assert receipt["target_alive_after_export"]
            trace = json.loads((output / "cpu-profile.json").read_text())
            receipt["trace_events"] = len(trace)
            assert receipt["trace_events"] > 0
            receipt["result"] = "PASS"
    finally:
        receipt["cleanup"] = owner.cleanup()
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    assert not receipt["cleanup"]["errors"]
    assert not receipt["cleanup"]["remaining_owned_pids"]
    print(json.dumps(receipt))


if __name__ == "__main__":
    if sys.argv[1] == "--launch":
        launch(Path(sys.argv[2]))
    else:
        run(Path(sys.argv[1]))
