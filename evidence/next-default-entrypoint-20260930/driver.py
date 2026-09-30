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
    parser.add_argument("--journey", default="default_entrypoint")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--review-existing", action="store_true",
                        help="Review retained native artifacts without launching the UI")
    args = parser.parse_args()
    sys.dont_write_bytecode = True  # Borrow the reviewed tools without writing to their WT.
    recorder_path = args.recorder.resolve()
    sys.path.insert(0, str(recorder_path.parent))
    spec = importlib.util.spec_from_file_location("default_entrypoint_recorder", recorder_path)
    recorder = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = recorder
    spec.loader.exec_module(recorder)

    class DefaultEntrypointJourney(recorder.PhysicalJourney):
        scope = "Saved original history, actual message focus, Home/Delete, A/B/A, End, close/reopen attachment"
        duration_seconds = 90

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

        @classmethod
        def verify(cls, base):
            return verify_editor_journey(base, args.thread)

    class DefaultHistoryReturnJourney(DefaultEntrypointJourney):
        """Affected238 startup and real tab return; no repeated keyboard journey."""

        scope = "Saved original history first paint and actual A/B/A tab return; no repeated keyboard/End journey"
        duration_seconds = 50

        @classmethod
        def script(cls, options):
            marker = recorder.marker_command()
            click = recorder.native_click_command
            return "\n".join([
                marker + "startup",
                click("phase-startup-state.pickle", target="thread", name=args.peer_thread),
                "sleep 2", marker + "peer-opened",
                click("phase-peer-opened-state.pickle", target="original_tab",
                      original_state="phase-startup-state.pickle"),
                "sleep 2", marker + "original-returned",
                "sleep 2", marker + "return-stationary", "",
            ])

        @classmethod
        def verify(cls, base):
            def phase(label):
                return pickle.loads((base / f"capture/phase-{label}-state.pickle").read_bytes())

            start = phase("startup")
            original = selected_view(start)
            peer = phase("peer-opened")
            returned = phase("original-returned")
            settled = phase("return-stationary")
            assert selected_view(peer)["identity"]["_comms_thread"] == args.peer_thread
            assert returned["metadata"]["current_mode"] == start["metadata"]["current_mode"]
            current = selected_view(settled)
            assert current["identity"]["_comms_thread"] == args.thread
            assert current["drafts"][0]["lines"] == original["drafts"][0]["lines"]
            assert current["drafts"][0]["object_id"] == original["drafts"][0]["object_id"]
            assert current["history_windows"][0]["object_id"] == original["history_windows"][0]["object_id"]
            return {"journey": cls.declared_name, "actual_A_B_A": True,
                    "editor_and_history_window_reused": True, "draft_unchanged": True,
                    "goal_start": original.get("goal"), "goal_return": current.get("goal"),
                    "goal_read_pending": "Not exposed by existing recorder DTO; no pending-goal fault injection",
                    "physical_frames_require_review": True}

    class DefaultBufferScrollJourney(DefaultEntrypointJourney):
        """One affected236 default scroll; no provider or keyboard-editor journey."""

        scope = "Actual default retained history buffer, focused PageUp/down/reverse/End/idle"
        duration_seconds = 65

        @classmethod
        def script(cls, options):
            return (recorder.marker_command() + "startup\n"
                    + recorder.scroll_script(idle_seconds=5, hold_seconds=3,
                                             state="phase-startup-state.pickle"))

        @classmethod
        def verify(cls, base):
            def phase(label):
                return pickle.loads((base / f"capture/phase-{label}-state.pickle").read_bytes())

            focused = phase("focused")
            window, = selected_view(focused)["history_windows"]
            assert focused["metadata"]["screen"]["focused"]["object_id"] == window["object_id"]
            observations = []
            for label in ("startup", "focused", "up-done", "down-done", "reverse-done", "idle", "idle-done"):
                state = phase(label)
                view = selected_view(state)
                current, = view["history_windows"]
                assert state["metadata"]["history_buffer_viewports"] == 3
                assert current["body_resources"]["budget"]["buffer_viewports"] == 3
                assert view["identity"]["_comms_thread"] == args.thread
                pages = [{"through": FieldCodec.encode(history["through"]),
                          "source_state": history["source_state"],
                          "pages": [{"before": FieldCodec.encode(page.before),
                                     "after": FieldCodec.encode(page.after),
                                     "event_count": len(page.events), "start": first, "stop": last}
                                    for page, first, last in history["pages"]]}
                         for history in view["history_pages"]]
                observations.append({"phase": label, "window": current, "pages": pages})
            return {"journey": cls.declared_name, "actual_history_focus": True,
                    "actual_setting_and_viewport_budget": 3,
                    "observations": observations, "physical_frames_require_review": True,
                    "no_full239_readiness_claim": True}

    command = ["/home/ts/bin/toad-comms", args.thread]
    journey = recorder.PhysicalJourney.decode(args.journey)
    from agent_comms.field_codec import FieldCodec

    def publish_read_review(base):
        checks = journey.verify(base)
        assert (base / "original-before.json").read_bytes() == (base / "original-after.json").read_bytes(), "Original native owner/source changed"
        (base / "scoped-native-review.json").write_text(json.dumps({
            "checks": checks, "source_and_owner_unchanged": True, "runtime_override": False,
            "prompt_submissions": 0, "physical_review": "Required before any default live PASS",
            "scope": journey.declared_name,
        }, indent=2) + "\n")

    if args.review_existing:
        base = args.output.resolve()
        receipt = json.loads((base / "capture/receipt.json").read_text())
        assert receipt["completed"] and receipt["capture_completed"]
        assert receipt["physical_journey"] == journey.declared_name
        publish_read_review(base)
        return
    actions = journey.script(None)
    preparation = {
        "command": command, "recorder": str(recorder_path),
        "recorder_sha256": hashlib.sha256(recorder_path.read_bytes()).hexdigest(),
        "peer_thread": args.peer_thread, "actions": actions,
        "journey": journey.declared_name,
        "launch_requires": "Parent explicitly announces reviewed default activation complete",
        "prepared_only": args.prepare_only,
        "scope": journey.scope,
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
                "--capture-target", "existing_thread", "--journey", journey.declared_name,
                "--capture-state", "--actions", str(action_file), "--review-timing", "deferred", "--fps", "30",
                "--width", "1280", "--height", "900", "--fit-window", "--startup-wait", "12",
                "--max-duration", str(journey.duration_seconds), "--tail-seconds", "2", "--", *command]
    try:
        recorder.main()
    finally:
        (base / "original-after.json").write_text(json.dumps(original(), indent=2) + "\n")

    publish_read_review(base)


def verify_editor_journey(base, thread):
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
    assert selected_view(phase("reopened"))["identity"]["_comms_thread"] == thread
    return checks


if __name__ == "__main__":
    main()
