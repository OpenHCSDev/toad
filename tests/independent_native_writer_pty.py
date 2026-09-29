"""Run one independent native cohort through the existing physical PTY owner."""
import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_pty import PtyLaunch, ToadSession


async def main():
    root = Path(__file__).resolve().parents[1]
    cohort = int(os.environ.get("WORKSPACE_LOADED_COHORTS", "4"))
    evidence = root / "evidence/native-writer-latency"
    stage = root / ".artifacts/native-tmp"
    stage.mkdir(parents=True, exist_ok=True)
    name = f"native-{cohort}"
    environment = dict(
        os.environ,
        AGENT_COMMS_ROOT=str(stage / "wrapper-wire"),
        TMPDIR=str(stage),
        AC_NATIVE_COPIED_PACKAGE=os.environ["AC_NATIVE_COPIED_PACKAGE"],
        L0A_EVIDENCE=str(evidence / name),
        NATIVE_RETENTION_RECEIPT=str(evidence / (name + ".json")),
        WORKSPACE_LOADED_COHORTS=str(cohort),
    )
    launch = PtyLaunch(
        (sys.executable, str(root / "tests/independent_native_writer_pilot.py")),
        root,
        environment,
    )
    session = ToadSession(launch)
    try:
        await session.start()
        if session.alive():
            session._set_size(44, 160)
        while session.alive():
            session._drain()
            await asyncio.sleep(.05)
        session._drain()
        await session.proc.wait()
        (evidence / (name + "-terminal.txt")).write_bytes(session.buffer)
        print("ACTUAL_PTY_NATIVE_WRITER_EXIT", session.proc.returncode, flush=True)
        if session.proc.returncode:
            print(session.buffer.decode("utf8", "replace")[-6000:])
            raise SystemExit(session.proc.returncode)
    finally:
        await session.stop()


if __name__ == "__main__":
    asyncio.run(main())
