"""Attachment freshness for already-decoded producer-owned observations."""

from __future__ import annotations

from agent_comms.acp_extension import (
    CursorEnvelope,
    CursorScope,
    QueueChangedUpdate,
    QueueScope,
)


class ProjectionAttachment:
    """One attachment, at most 32 pre-response receipts; no I/O or input effects.

    begin() must run when a trusted new/load request is *initiated*, not when
    its result arrives. The returned token fences overlapping/delayed results.
    """

    MAX_PREBIND = 32

    def __init__(self) -> None:
        self.current: CursorEnvelope | QueueChangedUpdate | None = None
        self.status: str | None = None
        self.quarantined = False
        self.floor: CursorScope | QueueScope | None = None
        self._buffer: list[tuple[str, CursorEnvelope]] = []
        # Scope-only invalidation evidence outlives disposable status receipts.
        # In particular begin() after uncertainty must not erase a newer generation
        # merely because an older in-flight result has not arrived yet.
        self._prebind_floors: dict[
            tuple[tuple[str, str, str], int | float], CursorScope | QueueScope
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

    def _observe_floor(self, scope: CursorScope | QueueScope) -> None:
        old = self.floor
        if (
            old is None
            or old.logical_key != scope.logical_key
            or old.owner_created_at != scope.owner_created_at
            or scope.admission_generation > old.admission_generation
        ):
            self.floor = scope

    def bind(
        self,
        value: CursorEnvelope | QueueChangedUpdate | None,
        session_id: str,
        token: int,
    ) -> str:
        if token != self._token:
            return "reject_old_request"
        if self._evidence_lost:
            self._quarantine()
            return "reject_evidence_lost"
        self._pending = False
        self._session_id = session_id
        envelope = value
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
                other.admission_generation == scope.admission_generation
                and other.owner_pid != scope.owner_pid
            ):
                self._uncertain = True
            elif other.admission_generation > scope.admission_generation:
                self._observe_floor(other)
            elif other == scope:
                matching.append(buffered)
        floor = self.floor
        if self._uncertain or (
            floor is not None
            and floor.logical_key == scope.logical_key
            and floor.owner_created_at == scope.owner_created_at
            and floor.admission_generation > scope.admission_generation
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

    def callback(
        self, value: CursorEnvelope | QueueChangedUpdate | None, session_id: str
    ) -> str:
        if self._session_id is not None and session_id != self._session_id:
            return "reject_foreign_session"
        if self._evidence_lost:
            return "reject_evidence_lost"
        if self.quarantined and not self._pending:
            return "reject_quarantined"
        envelope = value
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
                if other.admission_generation > previous.admission_generation:
                    self._prebind_floors[key] = other
            elif len(self._prebind_floors) < self.MAX_PREBIND:
                self._prebind_floors[key] = other
            else:
                # A distinct identity would lose an generation floor. Unlike receipt
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
            other.admission_generation == scope.admission_generation
            and other.owner_pid != scope.owner_pid
        ):
            self._quarantine(uncertain=True)
            return "quarantine_ambiguous"
        if other.admission_generation > scope.admission_generation:
            self._observe_floor(other)
            self._quarantine()
            return "quarantine_newer_generation"
        if other.admission_generation < scope.admission_generation:
            return "reject_stale_scope"
        return self._apply(envelope)

    def _apply(self, envelope: CursorEnvelope | QueueChangedUpdate) -> str:
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
