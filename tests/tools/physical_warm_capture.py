"""Run the existing physical recorder in a prepared private fixture callback."""

import argparse
import json
import os
from pathlib import Path
import shlex
import sys

from record_installed_tui import ProcessOwner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--session", required=True)
    parser.add_argument("--peer-thread", required=True)
    args = parser.parse_args()
    base = args.output.resolve()
    if not base.is_relative_to((Path.home() / ".cache/agent-scratch").resolve()):
        parser.error("Physical fixture evidence must be under owned persistent scratch")
    base.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    environment["XDG_STATE_HOME"] = str(base / "state")
    environment.pop("NO_COLOR", None)
    runtime = Path(environment["AGENT_COMMS_RUNTIME_ROOT"])
    recorder = Path(__file__).with_name("record_installed_tui.py").resolve()
    common = [str(runtime / "python"), str(recorder), "--journey", "warm_scroll",
              "--peer-thread", args.peer_thread, "--capture-state",
              "--scroll-hold-seconds", "4", "--scroll-idle-seconds", "15",
              "--max-duration", "100"]
    actions = base / "actions.xdo"
    command = [*common, "--private-root", environment["AGENT_COMMS_ROOT"],
               "--output", str(base / "capture"), "--owner", "Kepler236-physical-warm",
               "--actions", str(actions), "--fit-window", "--width", "1280", "--height", "900",
               "--startup-wait", "12", "--tail-seconds", "2",
               "--profile", "--profile-threads", "gil", "--profile-rate", "25",
               "--review-timing", "deferred", "--review-phase", "down", "--review-phase", "end",
               "--", str(runtime / "toad"), "acp",
               shlex.join([str(runtime / "python"), "-m", "agent_comms.acp"]),
               str(args.project), "--title", "Agent Comms", "--session", args.session]
    # Persist argv, never the retained launch environment/credentials.
    (base / "caller.json").write_text(json.dumps(command, indent=2) + "\n")
    owner = ProcessOwner()
    try:
        owner.run([*common, "--write-journey-script", str(actions)], environment, timeout=15)
        with (base / "recorder.log").open("w") as log:
            owner.run(command, environment, stdout=log, stderr=log, timeout=130)
    finally:
        (base / "caller-cleanup.json").write_text(json.dumps(owner.cleanup(), indent=2) + "\n")
    print(base / "capture/receipt.json", flush=True)


if __name__ == "__main__":
    main()
