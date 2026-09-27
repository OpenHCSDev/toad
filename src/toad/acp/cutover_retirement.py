"""Default-OFF, live-Toad-incarnation inventory for a future private-root cutover.

This module does not begin/advance a MaintenanceBarrier or publish a route.  Its
in-process fence only closes Toad's own *cooperative* start/send hooks.  The
caller must separately own a durable external PAUSE through retirement, fresh
inventory and route EX publication; no such production capability exists yet.
An arbitrary same-UID process, explicit-root external client, or descendant
which escaped an accepted process group is outside this registry's authority.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol

import psutil

from .group_retirement import AcceptedGroup, GroupRetirement


class RetirementUnresolved(RuntimeError):
    """No publishable controller-wide retirement conclusion is available."""


class RootFenced(RetirementUnresolved):
    """An enrolled Toad start or send targeted a locally fenced old root."""


class RetirableAgent(Protocol):
    """Only the reviewed Agent.stop/verify_retirement seam is needed."""

    async def stop(self) -> GroupRetirement | None: ...

    def verify_retirement(self) -> GroupRetirement: ...


class State(Enum):
    PREPARED = "prepared"  # child may still be admitted; never certify None
    ACCEPTED = "accepted"
    NO_CHILD = "no-child-after-settlement"
    RETIRED = "retired"
    UNKNOWN = "unknown"


@dataclass(eq=False)
class Enrollment:
    """Strongly holds the Agent, including after its widget/tab is detached."""

    agent: RetirableAgent
    root: Path
    implicit: bool
    state: State = State.PREPARED
    accepted: AcceptedGroup | None = None


@dataclass(frozen=True)
class RootFence:
    root: Path
    epoch: str
    generation: int


@dataclass(frozen=True)
class LiveIncarnationReceipt:
    """Scoped observation, intentionally not an EX-publication capability."""

    root: Path
    toad_pid: int
    toad_started_at: float
    controller_epoch: str
    fence_generation: int
    accepted: tuple[GroupRetirement, ...]
    scope: str = "live-toad-incarnation-enrolled-groups-only"
    publishable: bool = False


# The external PAUSE checker must fail if it is no longer held for this root.
# A lambda or test double can exercise the API, but cannot turn its explicitly
# non-publishable receipt into production EX authority.
PauseAssertion = Callable[[Path], None]
# This caller-owned inventory must reject known escaped descendants, unreadable
# processes and old-capable external/explicit-root clients.  The registry cannot
# derive that fact from its accepted process groups or mounted Toad tabs.
ExclusionAssertion = Callable[[Path, tuple[AcceptedGroup, ...]], None]


class Registry:
    """Cooperative single-event-loop inventory; inert until a root is fenced.

    Agent.start must register synchronously after freezing the child root and
    before its first await; Agent._run_agent must mark acceptance without an
    intervening await.  Every failed/cancelled admission may mark NO_CHILD only
    *after* admitted_spawn has settled and retired any unaccepted subprocess.
    An unregistered Agent is not covered by this scoped receipt.
    """

    def __init__(self) -> None:
        self._pid = os.getpid()
        self._started_at = psutil.Process(self._pid).create_time()
        self._epoch = uuid.uuid4().hex
        self._generation = 0
        self._entries: dict[int, Enrollment] = {}
        self._fences: dict[Path, RootFence] = {}

    def _assert_incarnation(self) -> None:
        if os.getpid() != self._pid:
            raise RetirementUnresolved("Toad incarnation changed")
        try:
            if psutil.Process(self._pid).create_time() != self._started_at:
                raise RetirementUnresolved("Toad process identity changed")
        except psutil.Error as error:
            raise RetirementUnresolved("Toad process identity unreadable") from error

    @staticmethod
    def _root(root: str | Path) -> Path:
        return Path(root).resolve()

    def require_open(self, root: str | Path) -> None:
        """Future Agent.start/send/reconnect hook; not a wire-lock PAUSE."""
        self._assert_incarnation()
        if self._root(root) in self._fences:
            raise RootFenced("old Toad ingress is locally fenced")

    def register_pre_spawn(
        self, agent: RetirableAgent, pinned_root: str | Path, *, implicit: bool
    ) -> Enrollment:
        """Enroll before the first asynchronous preflight or spawn boundary."""
        self.require_open(pinned_root)
        root = self._root(pinned_root)
        key = id(agent)
        existing = self._entries.get(key)
        if existing is not None and existing.agent is agent:
            if existing.state not in (State.NO_CHILD, State.RETIRED):
                raise RetirementUnresolved("Agent already has an unretired enrollment")
        entry = Enrollment(agent, root, implicit)
        self._entries[key] = entry
        return entry

    def _require_entry(self, entry: Enrollment) -> None:
        self._assert_incarnation()
        if self._entries.get(id(entry.agent)) is not entry:
            raise RetirementUnresolved("Agent enrollment is not current")

    def mark_accepted(self, entry: Enrollment, accepted: AcceptedGroup) -> None:
        self._require_entry(entry)
        if entry.state is not State.PREPARED:
            raise RetirementUnresolved("accepted child changed enrollment state")
        entry.accepted = accepted
        entry.state = State.ACCEPTED

    def mark_no_child(self, entry: Enrollment) -> None:
        """Only call after actual admission cleanup/denial has fully settled."""
        self._require_entry(entry)
        if entry.state is not State.PREPARED or entry.accepted is not None:
            raise RetirementUnresolved("cannot erase an accepted child")
        entry.state = State.NO_CHILD
        if entry.root not in self._fences:
            del self._entries[id(entry.agent)]

    def complete_normal_stop(
        self, entry: Enrollment, evidence: GroupRetirement
    ) -> None:
        """Do not drop an accepted identity until a fresh OS group check passes."""
        self._require_entry(entry)
        if entry.accepted is None or entry.accepted != evidence.accepted:
            raise RetirementUnresolved("normal stop group identity mismatched")
        from .group_retirement import verify_accepted_group

        verify_accepted_group(entry.accepted)
        entry.state = State.RETIRED
        if entry.root not in self._fences:
            del self._entries[id(entry.agent)]

    def mark_unknown(self, entry: Enrollment) -> None:
        """Pin uncertainty instead of manufacturing an empty child inventory."""
        self._require_entry(entry)
        entry.state = State.UNKNOWN

    def fence_old_root(self, root: str | Path) -> RootFence:
        """Synchronously deny new Toad ingress; NOT external durable PAUSE."""
        self._assert_incarnation()
        canonical = self._root(root)
        if canonical in self._fences:
            raise RetirementUnresolved("old-root fence already held")
        self._generation += 1
        fence = RootFence(canonical, self._epoch, self._generation)
        self._fences[canonical] = fence
        return fence

    def _require_fence(self, fence: RootFence) -> None:
        self._assert_incarnation()
        if fence.epoch != self._epoch or self._fences.get(fence.root) != fence:
            raise RetirementUnresolved("old-root fence is not current")

    def release_fence(self, fence: RootFence) -> None:
        """Operator-controlled abort/completion only; never publishes a route."""
        self._require_fence(fence)
        # Verify everything first.  A failed check must retain the fence and
        # strong references rather than reopening old ingress to a survivor.
        from .group_retirement import verify_accepted_group

        removable: list[int] = []
        for key, entry in self._entries.items():
            if entry.root != fence.root:
                continue
            if entry.state is State.NO_CHILD:
                removable.append(key)
            elif entry.state is State.RETIRED:
                if entry.accepted is None:
                    raise RetirementUnresolved("retired identity missing")
                verify_accepted_group(entry.accepted)
                removable.append(key)
            else:
                raise RetirementUnresolved("cannot release fence with unretired child")
        for key in removable:
            del self._entries[key]
        del self._fences[fence.root]

    async def retire_enrolled(
        self,
        fence: RootFence,
        *,
        assert_pause_current: PauseAssertion | None = None,
        assert_exclusions_clear: ExclusionAssertion | None = None,
    ) -> LiveIncarnationReceipt:
        """Retire only registered groups while an *external* PAUSE stays current.

        Both assertions are mandatory and must fail closed; they do not confer
        route-publication authority.  The caller must hold the real PAUSE and
        separately evaluate external writers through EX publication.
        """
        self._require_fence(fence)
        if assert_pause_current is None or assert_exclusions_clear is None:
            raise RetirementUnresolved("external PAUSE and exclusion checks required")
        assert_pause_current(fence.root)
        entries = tuple(e for e in self._entries.values() if e.root == fence.root)
        observed: list[GroupRetirement] = []
        for entry in entries:
            self._require_fence(fence)
            assert_pause_current(fence.root)
            if entry.state is State.UNKNOWN or entry.state is State.PREPARED:
                raise RetirementUnresolved("old child admission/identity unresolved")
            if entry.state is State.NO_CHILD:
                continue
            if entry.accepted is None:
                raise RetirementUnresolved("accepted group identity missing")
            if entry.state is State.ACCEPTED:
                result = await entry.agent.stop()
                self._require_fence(fence)
                assert_pause_current(fence.root)
                if result is None or result.accepted != entry.accepted:
                    raise RetirementUnresolved("stop supplied no matching group proof")
            fresh = entry.agent.verify_retirement()
            self._require_fence(fence)
            assert_pause_current(fence.root)
            if fresh.accepted != entry.accepted:
                raise RetirementUnresolved("fresh group proof changed identity")
            entry.state = State.RETIRED
            observed.append(fresh)
        # Rescan after the last await.  New entries cannot be enrolled through
        # this registry under the synchronous local fence, but fail if hooks
        # violated that contract or another path changed an enrollment.
        self._require_fence(fence)
        assert_pause_current(fence.root)
        current = tuple(e for e in self._entries.values() if e.root == fence.root)
        if current != entries:
            raise RetirementUnresolved("old-root enrollment changed during retirement")
        if any(
            e.state in (State.PREPARED, State.ACCEPTED, State.UNKNOWN)
            for e in current
        ):
            raise RetirementUnresolved("unretired old-root child remains")
        pinned = tuple(e.accepted for e in current if e.accepted is not None)
        assert_exclusions_clear(fence.root, pinned)
        self._require_fence(fence)
        assert_pause_current(fence.root)
        # Earlier groups may have been checked before later stop awaits.
        # Recheck every pinned original group in the final paused snapshot.
        from .group_retirement import verify_accepted_group

        observed = [verify_accepted_group(group) for group in pinned]
        self._require_fence(fence)
        assert_pause_current(fence.root)
        return LiveIncarnationReceipt(
            fence.root,
            self._pid,
            self._started_at,
            self._epoch,
            fence.generation,
            tuple(observed),
        )

    def assert_receipt_current(
        self, receipt: LiveIncarnationReceipt, fence: RootFence,
        assert_pause_current: PauseAssertion,
    ) -> None:
        """Reject stale incarnation/fence; does NOT upgrade receipt scope."""
        self._require_fence(fence)
        assert_pause_current(fence.root)
        if (
            receipt.toad_pid != self._pid
            or receipt.toad_started_at != self._started_at
            or receipt.controller_epoch != self._epoch
            or receipt.root != fence.root
            or receipt.fence_generation != fence.generation
            or receipt.publishable
        ):
            raise RetirementUnresolved("stale or upgraded Toad receipt")
        from .group_retirement import verify_accepted_group

        current = tuple(e for e in self._entries.values() if e.root == fence.root)
        if any(e.state not in (State.RETIRED, State.NO_CHILD) for e in current):
            raise RetirementUnresolved("new or unretired child after receipt")
        identities = tuple(e.accepted for e in current if e.accepted is not None)
        if identities != tuple(group.accepted for group in receipt.accepted):
            raise RetirementUnresolved("enrollment changed after receipt")
        for group in receipt.accepted:
            verify_accepted_group(group.accepted)
        self._require_fence(fence)
        assert_pause_current(fence.root)


# Hooks may import this singleton without activating any cutover or marker.
LIVE_TOAD_REGISTRY = Registry()
