"""Unsent physical editing on saved state through the existing installed recorder."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sqlite3
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--thread", default="nra-architecture")
    parser.add_argument("--peer", default="nra-domain-mapping")
    parser.add_argument("--runtime-bin", type=Path, help="Reviewed inactive candidate bin; omitted for the actual default launcher")
    parser.add_argument("--prompt-x", required=True, type=int)
    parser.add_argument("--prompt-y", required=True, type=int)
    parser.add_argument("--peer-x", required=True, type=int)
    parser.add_argument("--peer-y", required=True, type=int)
    parser.add_argument("--return-tab-x", required=True, type=int)
    parser.add_argument("--tab-y", required=True, type=int)
    parser.add_argument("--channel-x", required=True, type=int)
    parser.add_argument("--channel-y", required=True, type=int)
    args = parser.parse_args()
    base = args.output.expanduser().resolve()
    if not base.is_relative_to(Path.home() / ".cache/agent-scratch"):
        parser.error("Output must be in owned agent scratch")
    base.mkdir(parents=True, exist_ok=False)

    recorder_path = Path(__file__).with_name("record_installed_tui.py")
    spec = importlib.util.spec_from_file_location("editor_focus_recorder", recorder_path)
    recorder = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = recorder
    spec.loader.exec_module(recorder)

    class EditorFocusJourney(recorder.PhysicalJourney):
        @classmethod
        def script(cls, _args):
            marker = recorder.marker_command()
            prompt = f"mousemove --sync {args.prompt_x} {args.prompt_y}"
            edit = ["key Left Left BackSpace Delete Right"]
            return "\n".join([
                prompt, "click 1", "type --clearmodifiers --delay 80 abcdef", "sleep 1",
                marker + "typed", *edit, "sleep 1", marker + "edited",
                "mousemove --sync 750 350", "click 1", "key Prior", "sleep 1",
                "type --clearmodifiers --delay 80 abcdef", *edit, "sleep 1",
                marker + "history-edit",
                f"mousemove --sync {args.peer_x} {args.peer_y}", "click 1", "sleep 5",
                marker + "child-open",
                f"mousemove --sync {args.return_tab_x} {args.tab_y}", "click 1", "sleep 2",
                "type --clearmodifiers --delay 80 abcdef", *edit, "sleep 1",
                marker + "parent-return-edit",
                f"mousemove --sync {args.channel_x} {args.channel_y}", "click 1", "sleep 3",
                prompt, "click 1", "type --clearmodifiers --delay 80 abcdef", *edit, "sleep 1",
                marker + "channel-edit", "key ctrl+c",
                f"mousemove --sync {args.return_tab_x} {args.tab_y}", "click 1", "sleep 2",
                "type --clearmodifiers --delay 80 abcdef", *edit, "sleep 1",
                marker + "channel-return-edit", "key ctrl+c", "",
            ])

    # Copy only the UI database, not the active route, launch environment,
    # native journal or user configuration. No shared draft/undo is overwritten.
    source_db = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "toad/toad.db"
    target_db = base / "state/toad/toad.db"
    target_db.parent.mkdir(parents=True)
    with sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(target_db) as copied:
            original.backup(copied)
    os.environ["XDG_STATE_HOME"] = str(base / "state")
    for key in ("NO_COLOR", "PYTHONPATH", "AGENT_COMMS_RUNTIME_ROOT", "AGENT_COMMS_ACP_LAUNCHER"):
        os.environ.pop(key, None)
    if args.runtime_bin is not None:
        os.environ["AGENT_COMMS_RUNTIME_ROOT"] = str(args.runtime_bin.resolve())

    from agent_comms.comms import wire
    from agent_comms.field_codec import FieldCodec

    def originals():
        result = {}
        for name in (args.thread, args.peer):
            thread = wire().registry.require(name)
            path = Path(thread.session_file)
            result[name] = {"owner": FieldCodec.encode(thread.process_identity),
                            "parent": thread.parent, "bytes": path.stat().st_size,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "active_turn": FieldCodec.encode(thread.active_turn)}
        return result

    (base / "originals-before.json").write_text(json.dumps(originals(), indent=2))
    actions = base / "actions.xdo"
    actions.write_text(EditorFocusJourney.script(None))
    sys.argv = [str(recorder_path), "--output", str(base / "capture"), "--owner", "Kepler-Heisenberg227-editor-focus",
                "--capture-target", "existing_thread", "--journey", "editor_focus", "--capture-state",
                "--actions", str(actions),
                "--review-timing", "deferred", "--fps", "30", "--width", "1280", "--height", "900",
                "--fit-window", "--startup-wait", "12", "--max-duration", "100", "--tail-seconds", "2",
                "--", "/home/ts/bin/toad-comms", args.thread]
    try:
        recorder.main()
        events = [json.loads(line) for line in (base / "capture/events.jsonl").read_text().splitlines()]
        assert [event["label"] for event in events] == [
            "typed", "edited", "history-edit", "child-open", "parent-return-edit",
            "channel-edit", "channel-return-edit",
        ], "The physical editing journey did not complete"
    finally:
        (base / "originals-after.json").write_text(json.dumps(originals(), indent=2))

    # Read the recorder's native editor snapshots, never an alternate UI model.
    # Every assertion below is part of the same physical keystroke journey.
    expected = {
        "typed": ("abcdef", 6),
        "edited": ("abcf", 4),
        "history-edit": ("abcfabcf", 8),
        "child-open": ("", 0),
        "parent-return-edit": ("abcfabcfabcf", 12),
        "channel-edit": ("abcf", 4),
        "channel-return-edit": ("abcfabcfabcfabcf", 16),
    }
    observations = {}
    for phase, (text, column) in expected.items():
        snapshot = pickle.loads((base / f"capture/phase-{phase}-state.pickle").read_bytes())
        focus = snapshot["metadata"]["screen"]["focused"]
        draft = next(draft for view in snapshot["views"] for draft in view["drafts"]
                     if draft["object_id"] == focus["object_id"])
        observations[phase] = {
            "focused_editor": focus["object_id"], "class": focus["class"],
            "text": "\n".join(draft["lines"]), "selection": draft["selection"],
            "edit_passed": tuple(draft["lines"]) == (text,)
                           and draft["selection"] == ((0, column), (0, column)),
        }
    parent_phases = ("typed", "edited", "history-edit", "parent-return-edit", "channel-return-edit")
    result = {
        "phases": observations,
        "parent_editor_retained": len({observations[p]["focused_editor"] for p in parent_phases}) == 1,
        "originals_unchanged": (base / "originals-before.json").read_bytes()
                               == (base / "originals-after.json").read_bytes(),
    }
    (base / "editing-acceptance.json").write_text(json.dumps(result, indent=2))
    assert all(phase["edit_passed"] for phase in observations.values()), "Physical editor keys failed; see editing-acceptance.json"
    assert result["parent_editor_retained"], "Returning to the parent replaced its native editor"
    assert result["originals_unchanged"], "The readonly editing journey changed an original native thread"


if __name__ == "__main__":
    main()
