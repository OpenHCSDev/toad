"""Cooperative, local process-group retirement evidence for accepted ACP children.

This is not an escaped-descendant inventory or a route-publication permit.  A
controller must pause ingress and recheck the pinned group before publication.
"""

from __future__ import annotations

import os
import signal
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class AcceptedGroup:
    leader_pid: int
    leader_created_at: float
    pgid: int


@dataclass(frozen=True)
class GroupRetirement:
    accepted: AcceptedGroup
    members_at_check: tuple[tuple[int, float], ...]


class GroupRetirementUnresolved(RuntimeError):
    """The accepted group could not be proved empty; do not publish a route."""

    def __init__(
        self,
        accepted: AcceptedGroup | None,
        reason: str,
        members: tuple[tuple[int, float], ...] = (),
    ) -> None:
        self.accepted = accepted
        self.members = members
        super().__init__(reason)


def capture_accepted_group(pid: int) -> AcceptedGroup:
    """Pin the new-session shell before relying on its process-group identity."""
    try:
        if os.getpgid(pid) != pid:
            raise GroupRetirementUnresolved(
                None, "accepted child is not its group leader"
            )
        created_at = psutil.Process(pid).create_time()
    except (OSError, psutil.Error) as error:
        raise GroupRetirementUnresolved(
            None, "accepted child identity unavailable"
        ) from error
    return AcceptedGroup(pid, created_at, pid)


def live_group_members(accepted: AcceptedGroup) -> tuple[tuple[int, float], ...]:
    """Return non-zombie members, failing closed if group observation is uncertain."""
    members: list[tuple[int, float]] = []
    for process in psutil.process_iter():
        try:
            if os.getpgid(process.pid) != accepted.pgid:
                continue
            if process.status() == psutil.STATUS_ZOMBIE:
                continue
            members.append((process.pid, process.create_time()))
        except (ProcessLookupError, psutil.NoSuchProcess):
            continue
        except (OSError, psutil.Error) as error:
            raise GroupRetirementUnresolved(
                accepted, "cannot inspect accepted process group"
            ) from error
    return tuple(sorted(members))


def verify_accepted_group(accepted: AcceptedGroup) -> GroupRetirement:
    """Prove no non-zombie member remains, without clearing accepted identity."""
    members = live_group_members(accepted)
    if members:
        raise GroupRetirementUnresolved(
            accepted, "accepted process group remains live", members
        )
    return GroupRetirement(accepted, members)


def signal_accepted_group(accepted: AcceptedGroup, sig: signal.Signals) -> None:
    """Avoid signaling a newly reused leader PID/group after an identity change."""
    try:
        leader = psutil.Process(accepted.leader_pid)
        if leader.create_time() != accepted.leader_created_at:
            raise GroupRetirementUnresolved(accepted, "accepted leader PID was reused")
    except psutil.NoSuchProcess:
        # A group with surviving descendants retains its PGID even after the
        # leader exits.  An empty group needs no signal.
        if not live_group_members(accepted):
            return
    except psutil.Error as error:
        raise GroupRetirementUnresolved(
            accepted, "leader identity unavailable"
        ) from error
    try:
        os.killpg(accepted.pgid, sig)
    except ProcessLookupError:
        return
    except OSError as error:
        raise GroupRetirementUnresolved(
            accepted, "cannot signal accepted group"
        ) from error
