"""Read owned native phase snapshots; observations never control product state."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import pickle
from toad.transcript_preparation import CommittedInterval
from toad.widgets.transcript_history import TranscriptPageAdmission


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
    focused_widget: int | None
    loaded_pages: int
    admissions: tuple[TranscriptPageAdmission, ...]
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
        focused = snapshot["metadata"]["screen"]["focused"]
        admissions = tuple(TranscriptPageAdmission(
            CommittedInterval(page.before, page.after), start, stop,
        ) for history in view["history_pages"] for page, start, stop in history["pages"])
        return cls(label, mode, draft["object_id"], "\n".join(draft["lines"]), draft["selection"],
                   window["object_id"], focused["object_id"] if focused is not None else None,
                   len(admissions), admissions,
                   window["scroll_y"], window["maximum"],
                   window["follows_tail"], bodies)

    def ready_body_ids(self):
        return {body.object_id for body in self.bodies if body.ready}

    def admits_before(self, other: "NativePhase") -> bool:
        """Compare native admission, including expansion within a prepared page."""
        if not self.admissions or not other.admissions:
            return False
        current, previous = self.admissions[0], other.admissions[0]
        if current.interval == previous.interval:
            return current.start < previous.start
        return (current.interval.before != previous.interval.before
                and previous.interval.before.contains(current.interval.before))

    def admits_after(self, other: "NativePhase") -> bool:
        """The prepared page end alone does not describe its mounted body range."""
        if not self.admissions or not other.admissions:
            return False
        current, previous = self.admissions[-1], other.admissions[-1]
        if current.interval == previous.interval:
            return current.stop > previous.stop
        return (current.interval.through != previous.interval.through
                and current.interval.through.contains(previous.interval.through))


def review_retained_lifetime(output, receipt, *, suffix):
    """Review the saved-view lifetime variant without claiming scroll performance."""
    labels = ("warm-start", "draft", "reader-before-return", "b-open",
              "a-return", "undo", "lifetime-end")
    phases = {label: NativePhase.read(output, label) for label in labels}
    original, drafted, reader, peer, returned, undone, ended = (phases[label] for label in labels)
    same = (original, drafted, reader, returned, undone, ended)
    checks = {
        "original_saved_history_loaded": original.loaded_pages > 0,
        "peer_saved_history_loaded": peer.loaded_pages > 0,
        "peer_selected": peer.mode != original.mode,
        "source_view_retained": all(phase.mode == original.mode for phase in same),
        "editor_retained": all(phase.editor == original.editor for phase in same),
        "history_window_retained": all(phase.window == original.window for phase in same),
        "draft_typed": drafted.text == original.text + suffix,
        "draft_retained_on_return": returned.text == drafted.text,
        "undo_restored_original_draft": undone.text == original.text,
        "returned_saved_body_ready": any(body.ready and body.visible for body in returned.bodies),
        "end_saved_body_ready": any(body.ready and body.visible for body in ended.bodies),
    }
    result = {
        "checks": checks, "native_checks_passed": all(checks.values()),
        "phases": {label: asdict(phase) for label, phase in phases.items()},
        "physical_assessment": "unreviewed; inspect actual A/B/A and End PNGs/video",
        "scope": "saved application/source/resource lifetime, not warm raster/FPS/reader qualification",
        "events": [{"label": event["label"], "video_seconds": event["seconds_since_capture_launch"],
                    "screenshot": event.get("screenshot")}
                   for event in receipt["events"]],
    }
    (output / "retained-lifetime-review.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def review_warm_return(output, receipt, *, suffix):
    """Check actual draft/Undo and resource reuse, keeping physical review separate."""
    labels = ("warm-start", "draft", "focused", "up-done", "down-done", "reverse-done",
              "idle-done", "b-open", "a-return", "undo")
    phases = {label: NativePhase.read(output, label) for label in labels}
    initial, drafted = phases["warm-start"], phases["draft"]
    before_return, peer, returned, undone = (phases[label] for label in
                                            ("idle-done", "b-open", "a-return", "undo"))
    same = (initial, drafted, before_return, returned, undone)
    retained = before_return.ready_body_ids() & returned.ready_body_ids()
    focused, up, down, reversed_scroll = (phases[label] for label in
                                         ("focused", "up-done", "down-done", "reverse-done"))
    checks = {
        "original_saved_history_loaded": drafted.loaded_pages > 0,
        "peer_saved_history_loaded": peer.loaded_pages > 0,
        "history_scroll_extent": focused.maximum > 0,
        "scroll_keys_focus_history": all(phase.focused_widget == phase.window
                                          for phase in (focused, up, down, reversed_scroll)),
        "held_page_up_admitted_older_source": up.admits_before(focused),
        "held_page_down_admitted_newer_source": down.admits_after(up),
        "reverse_page_up_admitted_older_source": reversed_scroll.admits_before(down),
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
                         "Source admission direction does not certify visible motion; inspect the physical frames",
                         "A snapshot does not prove preparation or rasterization was skipped",
                         "Only actual Ctrl+Z output proves preserved Undo; no history-manager mirror is inspected"],
              "events": [{"label": event["label"], "video_seconds": event["seconds_since_capture_launch"],
                          "screenshot": event.get("screenshot"), "state_capture": event.get("state_capture")}
                         for event in receipt["events"]]}
    (output / "warm-scroll-review.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
