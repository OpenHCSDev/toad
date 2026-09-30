"""One input-free default journey through the existing isolated physical recorder."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sqlite3
import sys


def selected_view(snapshot):
    mode = snapshot["metadata"]["current_mode"]
    return next(view for view in snapshot["views"] if view["mode"] == mode)


def editor(snapshot):
    focus = snapshot["metadata"]["screen"]["focused"]
    draft, = (draft for draft in selected_view(snapshot)["drafts"]
              if draft["object_id"] == focus["object_id"])
    return "\n".join(draft["lines"]), draft["selection"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recorder", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--thread", default="nra-architecture")
    parser.add_argument("--peer-thread", default="nra-domain-mapping")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    sys.dont_write_bytecode = True  # Borrow the reviewed tools without writing to their WT.
    recorder_path = args.recorder.resolve()
    sys.path.insert(0, str(recorder_path.parent))
    spec = importlib.util.spec_from_file_location("default_entrypoint_recorder", recorder_path)
    recorder = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = recorder
    spec.loader.exec_module(recorder)

    class DefaultEntrypointJourney(recorder.PhysicalJourney):
        @classmethod
        def script(cls, options):
            marker = recorder.marker_command()
            click = recorder.native_click_command
            return "\n".join([
                marker + "startup", click("phase-startup-state.pickle"),
                "sleep .5", marker + "history-focused",
                click("phase-history-focused-state.pickle", target="editor"),
                "key ctrl+a", "sleep .5", marker + "editor-home",
                "type --clearmodifiers --delay 80 abcdef", "sleep .5", marker + "typed",
                "key Left Left BackSpace Delete Right", "sleep .5", marker + "edited",
                click("phase-edited-state.pickle", target="thread", name=args.peer_thread),
                "sleep 2", marker + "peer-opened",
                click("phase-peer-opened-state.pickle", target="original_tab",
                      original_state="phase-startup-state.pickle"),
                "sleep 2", marker + "original-returned",
                click("phase-original-returned-state.pickle", target="editor"),
                "key ctrl+a BackSpace", "sleep .5", marker + "home-backspace",
                "key Delete Delete Delete Delete", "sleep .5", marker + "draft-restored",
                click("phase-draft-restored-state.pickle"), "sleep .5",
                marker + "end-focused", "key End", "sleep 3", marker + "end-stationary",
                click("phase-end-stationary-state.pickle", target="original_tab",
                      original_state="phase-startup-state.pickle"),
                "click 2", "sleep 1", marker + "tab-closed",
                click("phase-tab-closed-state.pickle", target="thread", name=args.thread),
                "sleep 3", marker + "reopened", "",
            ])

    command = ["/home/ts/bin/toad-comms", args.thread]
    actions = DefaultEntrypointJourney.script(None)
    preparation = {
        "command": command, "recorder": str(recorder_path),
        "recorder_sha256": hashlib.sha256(recorder_path.read_bytes()).hexdigest(),
        "peer_thread": args.peer_thread, "actions": actions,
        "launch_requires": "Parent explicitly announces reviewed default activation complete",
        "prepared_only": args.prepare_only,
        "scope": "Saved original history, actual message focus, Home/Delete, A/B/A, End, close/reopen attachment",
        "reconnect": "Middle-click original tab label, then actual canonical roster reopening; no owner restart",
        "provider_calls": 0, "prompt_submissions": 0,
    }
    if args.prepare_only:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(preparation, indent=2) + "\n")
        return

    base = args.output.resolve()
    if not base.is_relative_to((Path.home() / ".cache/agent-scratch").resolve()):
        parser.error("Actual capture requires named persistent owned scratch")
    base.mkdir(parents=True, exist_ok=False)
    source = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "toad/toad.db"
    target = base / "state/toad/toad.db"
    target.parent.mkdir(parents=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as before:
        with sqlite3.connect(target) as copied:
            before.backup(copied)
    os.environ["XDG_STATE_HOME"] = str(base / "state")
    for key in ("NO_COLOR", "PYTHONPATH", "AGENT_COMMS_RUNTIME_ROOT", "AGENT_COMMS_ACP_LAUNCHER",
                "AGENT_COMMS_ROOT", "AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID", "AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE",
                "AGENT_COMMS_THREAD", "AGENT_COMMS_MANAGED", "PI_AGENT_ID", "PI_PARENT_ID", "PI_TASK", "PI_WORKTREE", "PI_PROMPT"):
        os.environ.pop(key, None)
    from agent_comms.comms import wire
    from agent_comms.field_codec import FieldCodec

    def original():
        thread = wire().registry.require(args.thread)
        path = Path(thread.session_file)
        return {"identity": FieldCodec.encode(thread.process_identity),
                "active_turn": FieldCodec.encode(thread.active_turn), "source_file": str(path),
                "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    peer = wire().registry.require(args.peer_thread)
    if peer.process_identity is None or not peer.process_identity.alive():
        raise ValueError("Peer must already be running; this check must not start native owners")
    (base / "original-before.json").write_text(json.dumps(original(), indent=2) + "\n")
    (base / "prepared-caller.json").write_text(json.dumps(preparation, indent=2) + "\n")
    action_file = base / "actions.xdo"
    action_file.write_text(actions)
    sys.argv = [str(recorder_path), "--output", str(base / "capture"), "--owner", "Einstein-default-entrypoint",
                "--capture-target", "existing_thread", "--journey", DefaultEntrypointJourney.declared_name,
                "--capture-state", "--actions", str(action_file), "--review-timing", "deferred", "--fps", "30",
                "--width", "1280", "--height", "900", "--fit-window", "--startup-wait", "12",
                "--max-duration", "90", "--tail-seconds", "2", "--", *command]
    try:
        recorder.main()
    finally:
        (base / "original-after.json").write_text(json.dumps(original(), indent=2) + "\n")

    def phase(label):
        return pickle.loads((base / f"capture/phase-{label}-state.pickle").read_bytes())

    focused = phase("history-focused")
    window, = (w for w in selected_view(focused)["history_windows"] if w["focus_target"] is not None)
    assert focused["metadata"]["screen"]["focused"]["object_id"] == window["object_id"], "Message area did not receive focus"
    baseline, home = editor(phase("editor-home"))
    assert home == ((0, 0), (0, 0)), home
    checks = {}
    for label, expected in (("typed", "abcdef" + baseline), ("edited", "abcf" + baseline),
                            ("home-backspace", "abcf" + baseline), ("draft-restored", baseline)):
        text, selection = editor(phase(label))
        checks[label] = {"text": text, "selection": selection}
        assert text == expected, (label, text, expected)
    start_mode = phase("startup")["metadata"]["current_mode"]
    returned = phase("original-returned")
    assert returned["metadata"]["current_mode"] == start_mode
    returned_draft, = selected_view(returned)["drafts"]
    assert "\n".join(returned_draft["lines"]) == "abcf" + baseline
    assert phase("peer-opened")["metadata"]["current_mode"] != start_mode
    assert start_mode not in phase("tab-closed")["metadata"]["open_tab_order"]
    assert selected_view(phase("reopened"))["identity"]["_comms_thread"] == args.thread
    assert (base / "original-before.json").read_bytes() == (base / "original-after.json").read_bytes(), "Original native owner/source changed"
    (base / "scoped-native-review.json").write_text(json.dumps({
        "checks": checks, "source_and_owner_unchanged": True, "runtime_override": False,
        "prompt_submissions": 0, "physical_review": "Required before any default live PASS",
        "scope": preparation["scope"],
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
