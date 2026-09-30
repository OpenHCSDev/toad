"""Observed stack transitions in py-spy's Chrome trace, never CPU spans.

Chrome B/E events compress unchanged sampled stacks. A span can remain open
while another thread owns the GIL, so duration and sample counts cannot be
recovered from these events. Kernel process counters remain CPU authority.
"""

from abc import abstractmethod
from dataclasses import dataclass
from itertools import groupby
import json
from collections import Counter
from pathlib import Path

from agent_comms.declared_family import DeclaredFamily


@dataclass(frozen=True)
class TraceFrame:
    function: str
    filename: str
    line: int


class TraceTransition(DeclaredFamily, affix="Transition"):
    @abstractmethod
    def apply(self, stack, frame: TraceFrame) -> None: ...


class BeginTransition(TraceTransition, declared_name="B"):
    def apply(self, stack, frame: TraceFrame) -> None:
        stack.append(frame)


class EndTransition(TraceTransition, declared_name="E"):
    def apply(self, stack, frame: TraceFrame) -> None:
        if not stack or stack.pop() != frame:
            raise ValueError("Unmatched py-spy Chrome stack transition")


@dataclass(frozen=True)
class TraceRecord:
    timestamp: int
    pid: int
    tid: int
    transition: TraceTransition
    frame: TraceFrame

    @classmethod
    def decode(cls, raw):
        return cls(raw["ts"], raw["pid"], raw["tid"],
                   TraceTransition.decode(raw["ph"])(),
                   TraceFrame(raw["name"], raw["args"]["filename"], raw["args"]["line"]))


@dataclass(frozen=True)
class StackObservation:
    timestamp: int
    pid: int
    tid: int
    frames: tuple[TraceFrame, ...]


class ProfileTrace:
    """Decode once, preserve trace order, observe each changed thread stack."""

    def __init__(self, path):
        self.records = tuple(TraceRecord.decode(raw) for raw in json.loads(path.read_text()))
        if any(before.timestamp > after.timestamp
               for before, after in zip(self.records, self.records[1:])):
            raise ValueError("py-spy Chrome transitions are not ordered")

    def observations(self):
        stacks = {}
        for timestamp, records in groupby(self.records, key=lambda record: record.timestamp):
            changed = set()
            for record in records:
                identity = record.pid, record.tid
                record.transition.apply(stacks.setdefault(identity, []), record.frame)
                changed.add(identity)
            for pid, tid in sorted(changed):
                frames = tuple(frame for frame in stacks[pid, tid] if frame.filename)
                if frames:
                    yield StackObservation(timestamp, pid, tid, frames)
        if any(stacks.values()):
            raise ValueError("py-spy Chrome trace ended with unclosed stacks")


@dataclass(frozen=True)
class FrameSelection:
    """Explicit source queries, not a second catalog of performance owners."""

    functions: tuple[str, ...]
    sources: tuple[str, ...]

    def accepts(self, frame: TraceFrame) -> bool:
        return ((not self.functions or frame.function in self.functions)
                and (not self.sources or any(source in frame.filename for source in self.sources)))


def review_phase_stacks(recording: Path, selection: FrameSelection, phases, examples: int):
    """Link complete observed stacks to the recorder's existing phase/CPU evidence."""
    from dataclasses import asdict

    review = json.loads((recording / "profile-review.json").read_text())
    unknown = set(phases) - {phase["label"] for phase in review["phases"]}
    if unknown:
        raise ValueError("Unknown retained phases: " + ", ".join(sorted(unknown)))
    observations = tuple(ProfileTrace(recording / review["trace"]).observations())
    offset = review["trace_to_video_offset_seconds"]
    result = {"recording": str(recording), "ui_pid": review["ui_pid"],
              "selection": asdict(selection), "profile": review["trace"],
              "alignment_nominal_uncertainty_seconds": review["alignment_nominal_uncertainty_seconds"],
              "limits": review["limits"] + [
                  "Matching stack groups are observed transitions, not sample counts, calls or CPU time",
                  "No observed match does not prove work was absent; async await parents may be missing",
                  "Complete matching stacks supplement the capped recorder preview; raw source remains authoritative"],
              "phases": []}
    for phase in review["phases"]:
        if phases and phase["label"] not in phases:
            continue
        within = tuple(observation for observation in observations
                       if phase["video_start_seconds"] <= observation.timestamp / 1_000_000 + offset
                       < phase["video_end_seconds"])
        matching = tuple(observation for observation in within
                         if any(selection.accepts(frame) for frame in observation.frames))
        frames = Counter((observation.pid, observation.tid, frame)
                         for observation in matching for frame in set(observation.frames)
                         if selection.accepts(frame))
        result["phases"].append({
            "label": phase["label"], "video_start_seconds": phase["video_start_seconds"],
            "video_end_seconds": phase["video_end_seconds"],
            "kernel_cpu": [{key: cpu[key] for key in ("pid", "cpu_seconds", "average_cpu_percent")}
                           for cpu in phase["cpu"]], "physical_evidence": phase["physical_evidence"],
            "observed_stack_groups": len(within), "matching_stack_groups": len(matching),
            "matched_frames": [{"pid": pid, "tid": tid, **asdict(frame),
                                "stack_presence_transition_groups": count}
                               for (pid, tid, frame), count in frames.most_common()],
            "complete_stack_examples": [
                {"video_seconds": observation.timestamp / 1_000_000 + offset,
                 "pid": observation.pid, "tid": observation.tid,
                 "frames": [asdict(frame) for frame in observation.frames]}
                for observation in matching[:examples]],
        })
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Query complete retained physical phase stacks; never launch an app")
    parser.add_argument("recording", type=Path)
    parser.add_argument("--function", action="append", default=[])
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--phase", action="append", default=[])
    parser.add_argument("--examples", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.examples < 0:
        parser.error("Examples cannot be negative")
    result = review_phase_stacks(args.recording.resolve(),
                                FrameSelection(tuple(args.function), tuple(args.source)),
                                args.phase, args.examples)
    with args.output.open("x") as output:
        json.dump(result, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
