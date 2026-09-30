"""Read owned native phase snapshots; observations never control product state."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import pickle


@dataclass(frozen=True)
class BodyObservation:
    object_id: int
    ready: bool
    dormant: bool
    visible: bool
    measured_rows: int


@dataclass(frozen=True)
class NativePhase:
    """Decode the recorder's retained DTO once at its diagnostic boundary."""

    label: str
    mode: str
    editor: int
    text: str
    selection: tuple
    window: int
    scroll_y: float
    maximum: float
    follows_tail: bool
    bodies: tuple[BodyObservation, ...]

    @classmethod
    def read(cls, output: Path, label: str):
        # These are our own trusted capture files, not external user pickles.
        snapshot = pickle.loads((output / f"phase-{label}-state.pickle").read_bytes())
        mode = snapshot["metadata"]["current_mode"]
        view, = (view for view in snapshot["views"] if view["mode"] == mode)
        draft, = view["drafts"]
        window, = view["history_windows"]
        bodies = tuple(BodyObservation(body["object_id"], body["ready"], body["dormant"],
                                       body["visible"], body["measured_rows"])
                       for body in window["body_resources"]["owners"])
        return cls(label, mode, draft["object_id"], "\n".join(draft["lines"]), draft["selection"],
                   window["object_id"], window["scroll_y"], window["maximum"], window["follows_tail"], bodies)

    def ready_body_ids(self):
        return {body.object_id for body in self.bodies if body.ready}


def review_warm_return(output, receipt, *, suffix):
    """Check actual draft/Undo and resource reuse, keeping physical review separate."""
    labels = ("warm-start", "draft", "idle-done", "b-open", "a-return", "undo")
    phases = {label: NativePhase.read(output, label) for label in labels}
    initial, drafted = phases["warm-start"], phases["draft"]
    before_return, peer, returned, undone = (phases[label] for label in
                                            ("idle-done", "b-open", "a-return", "undo"))
    same = (initial, drafted, before_return, returned, undone)
    retained = before_return.ready_body_ids() & returned.ready_body_ids()
    checks = {
        "draft_typed": drafted.text == initial.text + suffix,
        "peer_selected": peer.mode != initial.mode,
        "source_retained": all(phase.mode == initial.mode for phase in same),
        "editor_retained": all(phase.editor == initial.editor for phase in same),
        "history_window_retained": all(phase.window == initial.window for phase in same),
        "draft_retained": returned.text == drafted.text,
        "reader_position_retained": returned.scroll_y == before_return.scroll_y,
        "ready_body_resources_retained": bool(retained),
        "undo_restored_original_draft": undone.text == initial.text,
    }
    result = {"checks": checks, "native_checks_passed": all(checks.values()),
              "retained_ready_body_ids": sorted(retained),
              "phases": {label: asdict(phase) for label, phase in phases.items()},
              "physical_assessment": "unreviewed; inspect terminal.mp4 and phase PNGs",
              "limits": ["Native resource identities do not certify a warm physical first paint",
                         "A snapshot does not prove preparation or rasterization was skipped",
                         "Only actual Ctrl+Z output proves preserved Undo; no history-manager mirror is inspected"],
              "events": [{"label": event["label"], "video_seconds": event["seconds_since_capture_launch"],
                          "screenshot": event.get("screenshot"), "state_capture": event.get("state_capture")}
                         for event in receipt["events"]]}
    (output / "warm-scroll-review.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
