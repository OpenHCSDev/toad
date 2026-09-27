"""Bounded, read-only native-history provenance. Never input disposition.

Only validated scope/status/revision and a payload digest survive parsing; raw
proof identifiers/content are not passed to the presentation layer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

CursorStatus = Literal["proven", "coverage_only", "none", "unavailable"]
LABELS = {
    "proven": "Native history: selected source proof available",
    "coverage_only": "Native history: source coverage only (no injected input)",
    "none": "Native history: no current-owner cursor",
    "unavailable": "Native history: unavailable",
}
TOOLTIP = "Read-only provenance, not input acceptance, consumption, completion or ACK."
MAX_ENVELOPE_BYTES = 16_384
_HEX_ID = re.compile(r"[0-9a-f]{32}\Z")


def _integer(value: object, minimum: int = 1) -> bool:
    return type(value) is int and minimum <= value <= 2**63 - 1


def _text(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 1024


@dataclass(frozen=True)
class CursorScope:
    session_id: str
    wire_root_id: str
    owner_thread: str
    owner_created_at: int | float
    owner_pid: int
    owner_epoch: int

    @property
    def logical_key(self) -> tuple[str, str, str]:
        return self.session_id, self.wire_root_id, self.owner_thread


@dataclass(frozen=True)
class CursorEnvelope:
    scope: CursorScope | None
    revision: int
    status: CursorStatus
    digest: str


def parse_cursor(value: object) -> CursorEnvelope | None:
    """Strict v1 boundary; malformed/oversized data never becomes proof."""
    if not isinstance(value, dict):
        return None
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except TypeError, ValueError, RecursionError:
        return None
    if len(encoded) > MAX_ENVELOPE_BYTES:
        return None
    if type(value.get("version")) is not int or value["version"] != 1:
        return None
    revision = value.get("revision")
    status = value.get("status")
    if not _integer(revision) or not isinstance(status, str) or status not in LABELS:
        return None
    raw_scope = value.get("scope")
    if "scope" not in value:
        return None
    scope = None
    if raw_scope is not None:
        if not isinstance(raw_scope, dict):
            return None
        session, root, owner = (
            raw_scope.get(key) for key in ("sessionId", "wireRootId", "ownerThread")
        )
        created, pid, epoch = (
            raw_scope.get(key) for key in ("ownerCreatedAt", "ownerPid", "ownerEpoch")
        )
        if (
            not _text(session)
            or not _text(owner)
            or not isinstance(root, str)
            or not _HEX_ID.fullmatch(root)
            or type(created) not in (int, float)
            or not (0 < created <= 2**63 - 1)
            or not _integer(pid)
            or not _integer(epoch)
        ):
            return None
        scope = CursorScope(session, root, owner, created, pid, epoch)
    if status in ("proven", "coverage_only"):
        if scope is None:
            return None
        if (
            value.get("wire_root_id") != scope.wire_root_id
            or value.get("owner_thread") != scope.owner_thread
            or not _integer(value.get("owner_admission_epoch"))
            or value["owner_admission_epoch"] != scope.owner_epoch
            or not _text(value.get("recipient_lookup"))
            or not _integer(value.get("owner_generation"))
            or not _integer(value.get("covered_seq"), 0)
            or not _integer(value.get("injected_seq"), 0)
            or value["injected_seq"] > value["covered_seq"]
        ):
            return None
        proof_keys = (
            "input_id",
            "claim_id",
            "stage",
            "session_id",
            "request_generation",
        )
        if status == "coverage_only":
            if value["injected_seq"] != 0 or any(
                key not in value or value[key] is not None for key in proof_keys
            ):
                return None
        elif (
            value["injected_seq"] == 0
            or not isinstance(value.get("input_id"), str)
            or not _HEX_ID.fullmatch(value["input_id"])
            or not all(
                _text(value.get(key)) for key in ("claim_id", "stage", "session_id")
            )
            or not _integer(value.get("request_generation"))
        ):
            return None
    elif scope is None and status != "unavailable":
        return None
    return CursorEnvelope(scope, revision, status, sha256(encoded).hexdigest())


class CursorReducer:
    """One attachment, at most 32 pre-response receipts; no I/O or input effects.

    begin() must run when a trusted new/load request is *initiated*, not when
    its result arrives. The returned token fences overlapping/delayed results.
    """

    MAX_PREBIND = 32

    def __init__(self) -> None:
        self.current: CursorEnvelope | None = None
        self.status: CursorStatus | None = None
        self.quarantined = False
        self.floor: CursorScope | None = None
        self._buffer: list[tuple[str, CursorEnvelope]] = []
        # Scope-only invalidation evidence outlives disposable status receipts.
        # In particular begin() after uncertainty must not erase a newer epoch
        # merely because an older in-flight result has not arrived yet.
        self._prebind_floors: dict[
            tuple[tuple[str, str, str], int | float], CursorScope
        ] = {}
        self._uncertain = False
        self._evidence_lost = False
        self._pending = True
        self._token = 0
        self._session_id: str | None = None

    def begin(self, session_id: str | None) -> int:
        self._token += 1
        self._session_id = session_id
        self._pending = True
        # Only a newly initiated explicit request can retire ambiguity/overflow.
        if self._uncertain:
            self._buffer.clear()
            self._uncertain = False
        if self.status is not None:
            self.status = "unavailable"
        return self._token

    def is_current_request(self, token: int) -> bool:
        """Fence Agent session/metadata mutation as well as reducer binding."""
        return token == self._token

    def invalidate(self) -> None:
        self.status = "unavailable" if self.status is not None else None
        self.quarantined = True
        self._uncertain = True
        self._pending = False
        self._token += 1

    def _quarantine(self, *, uncertain: bool = False) -> None:
        self.status = "unavailable"
        self.quarantined = True
        self._uncertain |= uncertain

    def _observe_floor(self, scope: CursorScope) -> None:
        old = self.floor
        if (
            old is None
            or old.logical_key != scope.logical_key
            or old.owner_created_at != scope.owner_created_at
            or scope.owner_epoch > old.owner_epoch
        ):
            self.floor = scope

    def bind(self, value: object, session_id: str, token: int) -> str:
        if token != self._token:
            return "reject_old_request"
        if self._evidence_lost:
            self._quarantine()
            return "reject_evidence_lost"
        self._pending = False
        self._session_id = session_id
        envelope = parse_cursor(value)
        if (
            envelope is None
            or envelope.scope is None
            or envelope.scope.session_id != session_id
        ):
            self._quarantine(uncertain=True)
            # Hide absent metadata on ordinary non-private sessions.
            if value is None and self.current is None and not self._buffer:
                self.status = None
            return "reject_unavailable_binding"
        scope = envelope.scope
        observed = self._prebind_floors.get((scope.logical_key, scope.owner_created_at))
        if observed is not None:
            self._observe_floor(observed)
        matching = []
        for receiving_session, buffered in self._buffer:
            other = buffered.scope
            if (
                receiving_session != session_id
                or other.logical_key != scope.logical_key
            ):
                continue
            if other.owner_created_at != scope.owner_created_at or (
                other.owner_epoch == scope.owner_epoch
                and other.owner_pid != scope.owner_pid
            ):
                self._uncertain = True
            elif other.owner_epoch > scope.owner_epoch:
                self._observe_floor(other)
            elif other == scope:
                matching.append(buffered)
        floor = self.floor
        if self._uncertain or (
            floor is not None
            and floor.logical_key == scope.logical_key
            and floor.owner_created_at == scope.owner_created_at
            and floor.owner_epoch > scope.owner_epoch
        ):
            self._quarantine()
            return "reject_binding_floor_or_uncertainty"
        if (
            self.current is not None
            and self.current.scope == scope
            and (
                envelope.revision < self.current.revision
                or (
                    envelope.revision == self.current.revision
                    and envelope.digest != self.current.digest
                )
            )
        ):
            self._quarantine(uncertain=True)
            return "reject_stale_or_conflicting_binding"
        self.current = envelope
        self.status = envelope.status
        self.quarantined = False
        self._observe_floor(scope)
        self._buffer.clear()
        self._prebind_floors.clear()
        for buffered in sorted(matching, key=lambda item: item.revision):
            self._apply(buffered)
        return "bind"

    def callback(self, value: object, session_id: str) -> str:
        if self._session_id is not None and session_id != self._session_id:
            return "reject_foreign_session"
        if self._evidence_lost:
            return "reject_evidence_lost"
        if self.quarantined and not self._pending:
            return "reject_quarantined"
        envelope = parse_cursor(value)
        if envelope is None or envelope.scope is None:
            self._quarantine(uncertain=True)
            return "quarantine_unavailable"
        if envelope.scope.session_id != session_id:
            return "reject_foreign_session"
        if self._pending or self.current is None:
            other = envelope.scope
            if self.current is not None:
                incumbent = self.current.scope
                if (
                    other.logical_key == incumbent.logical_key
                    and other.owner_created_at == incumbent.owner_created_at
                ):
                    self._observe_floor(other)
            key = other.logical_key, other.owner_created_at
            previous = self._prebind_floors.get(key)
            if previous is not None:
                if other.owner_epoch > previous.owner_epoch:
                    self._prebind_floors[key] = other
            elif len(self._prebind_floors) < self.MAX_PREBIND:
                self._prebind_floors[key] = other
            else:
                # A distinct identity would lose an epoch floor. Unlike receipt
                # overflow, no later result on this attachment can prove it
                # superseded the discarded observation. Require a fresh Agent.
                self._evidence_lost = True
                self._quarantine(uncertain=True)
                return "quarantine_evidence_lost"
            if len(self._buffer) == self.MAX_PREBIND:
                self._quarantine(uncertain=True)
                return "quarantine_overflow"
            self._buffer.append((session_id, envelope))
            self.status = "unavailable"
            return "buffer"
        scope, other = self.current.scope, envelope.scope
        if other.logical_key != scope.logical_key:
            return "reject_foreign_scope"
        if other.owner_created_at != scope.owner_created_at or (
            other.owner_epoch == scope.owner_epoch
            and other.owner_pid != scope.owner_pid
        ):
            self._quarantine(uncertain=True)
            return "quarantine_ambiguous"
        if other.owner_epoch > scope.owner_epoch:
            self._observe_floor(other)
            self._quarantine()
            return "quarantine_newer_epoch"
        if other.owner_epoch < scope.owner_epoch:
            return "reject_stale_scope"
        return self._apply(envelope)

    def _apply(self, envelope: CursorEnvelope) -> str:
        if envelope.revision < self.current.revision:
            return "reject_stale_revision"
        if envelope.revision == self.current.revision:
            return (
                "duplicate"
                if envelope.digest == self.current.digest
                else "reject_equal_revision_conflict"
            )
        self.current = envelope
        self.status = envelope.status
        return "accept"
