"""Observed stack transitions in py-spy's Chrome trace, never CPU spans.

Chrome B/E events compress unchanged sampled stacks. A span can remain open
while another thread owns the GIL, so duration and sample counts cannot be
recovered from these events. Kernel process counters remain CPU authority.
"""

from abc import abstractmethod
from dataclasses import dataclass
from itertools import groupby
import json

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
