"""Exact-ID read-only queue projection. Not input disposition or retry authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MAX_ROWS = 32
MAX_TEXT_BYTES = 4096
MAX_TOTAL_BYTES = 65536
MAX_PREBIND = 32
MAX_TOMBSTONES = 4096


def integer(value: object, minimum: int = 1) -> bool:
    return type(value) is int and minimum <= value <= 2**63 - 1


def identifier(value: object) -> bool:
    if not isinstance(value, str) or not 0 < len(value) <= 1024:
        return False
    try:
        return len(value.encode("utf-8")) <= 4096
    except UnicodeError:
        return False


@dataclass(frozen=True)
class QueueScope:
    session_id: str
    owner_thread: str
    owner_created_at: int | float
    owner_epoch: int
    admission_generation: int

    @property
    def logical_key(self):
        return self.session_id, self.owner_thread

    @property
    def owner_key(self):
        return (
            self.owner_thread,
            self.owner_created_at,
            self.owner_epoch,
            self.admission_generation,
        )


def parse_scope(value: object, *, binding: bool = False) -> QueueScope | None:
    if not isinstance(value, dict):
        return None
    if binding and (type(value.get("version")) is not int or value["version"] != 1):
        return None
    session, owner = value.get("sessionId"), value.get("ownerThread")
    created = value.get("ownerCreatedAt")
    epoch, generation = value.get("ownerEpoch"), value.get("admissionGeneration")
    if (
        not identifier(session)
        or not identifier(owner)
        or type(created) not in (int, float)
        or not 0 < created <= 2**63 - 1
        or not integer(epoch)
        or not integer(generation)
        or epoch != generation
    ):
        return None
    return QueueScope(session, owner, created, epoch, generation)


@dataclass(frozen=True)
class QueueItem:
    input_id: str
    text: str


@dataclass(frozen=True)
class QueueEvent:
    kind: Literal["queueState", "inputStarted"]
    scope: QueueScope
    revision: int
    items: tuple[QueueItem, ...] = ()
    restored: tuple[QueueItem, ...] = ()
    input_id: str | None = None
    text: str | None = None

    @property
    def digest(self) -> tuple:
        # Compare normalized, bounded semantics; never serialize/traverse
        # arbitrary extra metadata just to fingerprint a receipt.
        return (
            self.kind,
            self.scope,
            self.revision,
            self.items,
            self.restored,
            self.input_id,
            self.text,
        )


def text_bytes(value: object) -> int | None:
    if not isinstance(value, str) or len(value) > MAX_TEXT_BYTES:
        return None
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        return None
    return size if size <= MAX_TEXT_BYTES else None


def parse_event(kind: str, value: object) -> QueueEvent | None:
    if not isinstance(value, dict) or kind not in ("queueState", "inputStarted"):
        return None
    if type(value.get("version")) is not int or value["version"] != 1:
        return None
    scope = parse_scope(value.get("scope"))
    if scope is None or not integer(value.get("revision")):
        return None
    if kind == "inputStarted":
        input_id, text = value.get("inputId"), value.get("text")
        if not identifier(input_id) or "text" not in value:
            return None
        if text is not None and text_bytes(text) is None:
            return None
        return QueueEvent(kind, scope, value["revision"], input_id=input_id, text=text)
    items, restored = value.get("items"), value.get("restored")
    if not isinstance(items, list) or not isinstance(restored, list):
        return None
    if len(items) + len(restored) > MAX_ROWS:
        return None
    seen, size = set(), 0
    parsed = []
    for rows in (items, restored):
        group = []
        for row in rows:
            if not isinstance(row, dict) or not identifier(row.get("inputId")):
                return None
            input_id, text = row["inputId"], row.get("text")
            count = text_bytes(text)
            if input_id in seen or count is None:
                return None
            size += count
            if size > MAX_TOTAL_BYTES:
                return None
            seen.add(input_id)
            group.append(QueueItem(input_id, text))
        parsed.append(tuple(group))
    return QueueEvent(kind, scope, value["revision"], *parsed)


@dataclass(frozen=True)
class QueueProjection:
    status: Literal["available", "unavailable"] | None = None
    items: tuple[QueueItem, ...] = ()
    restored: tuple[QueueItem, ...] = ()


class QueueReducer:
    """One Agent attachment. All mutations here affect presentation only."""

    def __init__(self, session_id: str | None = None) -> None:
        self.scope: QueueScope | None = None
        self.revision = 0
        self._digest: tuple | None = None
        self._kind = ""
        self.projection = QueueProjection()
        self._retired: set[str] = set()
        self._buffer: list[QueueEvent] = []
        self._floors: dict[tuple, QueueScope] = {}
        self._pending = True
        self._uncertain = False
        self._evidence_lost = False
        self._quarantined = False
        self._token = 0
        self._session_id = session_id

    def begin(self, session_id: str | None) -> int:
        self._token += 1
        self._session_id = session_id
        self._pending = True
        if self._uncertain:
            self._buffer.clear()
            self._uncertain = False
        if self.projection.status is not None:
            self.projection = QueueProjection("unavailable")
        return self._token

    def invalidate(self) -> None:
        self._token += 1
        self._pending = False
        if self.projection.status is None:
            self._quarantined = True
            return
        self._hide(uncertain=True)

    def _hide(self, *, uncertain=False, lost=False) -> None:
        self.projection = QueueProjection("unavailable")
        self._quarantined = True
        self._uncertain |= uncertain
        self._evidence_lost |= lost

    def _floor(self, scope: QueueScope) -> bool:
        key = scope.logical_key, scope.owner_created_at
        old = self._floors.get(key)
        if old is None:
            if len(self._floors) >= MAX_PREBIND:
                self._hide(lost=True)
                return False
            self._floors[key] = scope
        elif scope.owner_epoch > old.owner_epoch:
            self._floors[key] = scope
        return True

    @staticmethod
    def _relation(scope: QueueScope, other: QueueScope) -> str:
        if other.logical_key != scope.logical_key:
            return "foreign"
        if other.owner_created_at != scope.owner_created_at or (
            other.owner_epoch == scope.owner_epoch
            and other.admission_generation != scope.admission_generation
        ):
            return "ambiguous"
        if other.owner_epoch > scope.owner_epoch:
            return "newer"
        if other.owner_epoch < scope.owner_epoch:
            return "older"
        return "same"

    def bind(
        self, binding: object, state: object, session: str, token: int
    ) -> tuple[str, tuple[QueueItem, ...]]:
        if token != self._token:
            return "reject_old_request", ()
        self._pending = False
        self._session_id = session
        if self._evidence_lost:
            self._hide()
            return "reject_evidence_lost", ()
        scope, snapshot = parse_scope(binding, binding=True), parse_event(
            "queueState", state
        )
        if (
            scope is None
            or snapshot is None
            or snapshot.scope != scope
            or scope.session_id != session
        ):
            self._hide(uncertain=True)
            return "reject_unavailable_binding", ()
        floor = self._floors.get((scope.logical_key, scope.owner_created_at))
        if floor is not None and floor.owner_epoch > scope.owner_epoch:
            self._hide()
            return "reject_binding_floor", ()
        matching = []
        for event in self._buffer:
            relation = self._relation(scope, event.scope)
            if relation in ("ambiguous", "newer"):
                self._hide(uncertain=relation == "ambiguous")
                return "reject_binding_scope", ()
            if relation == "same":
                matching.append(event)
        if self._uncertain:
            self._hide()
            return "reject_uncertain_binding", ()
        if self.scope == scope and (
            snapshot.revision < self.revision
            or (
                snapshot.revision == self.revision
                and (self._kind != snapshot.kind or self._digest != snapshot.digest)
            )
        ):
            self._hide(uncertain=True)
            return "reject_stale_binding", ()
        if self.scope is None or self.scope.owner_key != scope.owner_key:
            self._retired.clear()
        if self._retired.intersection(
            row.input_id for row in snapshot.items + snapshot.restored
        ):
            self._hide(uncertain=True)
            return "reject_resurrection", ()
        self.scope = scope
        self.revision, self._digest, self._kind = (
            snapshot.revision,
            snapshot.digest,
            snapshot.kind,
        )
        self.projection = QueueProjection(
            "available", snapshot.items, snapshot.restored
        )
        self._quarantined = False
        self._buffer.clear()
        self._floors = {(scope.logical_key, scope.owner_created_at): scope}
        starts = []
        for event in sorted(matching, key=lambda event: event.revision):
            if self._quarantined:
                break
            _, echo = self._apply(event)
            starts.extend(echo)
        return "bind", tuple(starts)

    def callback(
        self, kind: str, value: object, session: str
    ) -> tuple[str, tuple[QueueItem, ...]]:
        if self._session_id is not None and session != self._session_id:
            return "reject_foreign_session", ()
        if self._evidence_lost:
            return "reject_quarantined", ()
        event = parse_event(kind, value)
        if event is None:
            self._hide(uncertain=True)
            return "reject_unavailable", ()
        if event.scope.session_id != session:
            return "reject_foreign_session", ()
        if self._quarantined and not self._pending:
            # Hidden presentation is not permission to forget newer validated
            # owner evidence before the next explicitly initiated load.
            relation = (
                self._relation(self.scope, event.scope) if self.scope else "newer"
            )
            if relation not in ("foreign", "older"):
                self._floor(event.scope)
                self._uncertain |= relation == "ambiguous"
            return "reject_quarantined", ()
        if self._pending or self.scope is None:
            if not self._floor(event.scope):
                return "reject_evidence_lost", ()
            if len(self._buffer) >= MAX_PREBIND:
                self._hide(uncertain=True)
                return "reject_overflow", ()
            self._buffer.append(event)
            self.projection = QueueProjection("unavailable")
            return "buffer", ()
        relation = self._relation(self.scope, event.scope)
        if relation == "foreign":
            return "reject_foreign_scope", ()
        if relation == "older":
            return "reject_stale_scope", ()
        if relation in ("ambiguous", "newer"):
            self._floor(event.scope)
            self._hide(uncertain=relation == "ambiguous")
            return "quarantine_scope", ()
        return self._apply(event)

    def _apply(self, event: QueueEvent) -> tuple[str, tuple[QueueItem, ...]]:
        if event.revision < self.revision:
            return "reject_stale_revision", ()
        if event.revision == self.revision:
            return (
                "duplicate"
                if (event.digest, event.kind) == (self._digest, self._kind)
                else "reject_equal_revision_conflict"
            ), ()
        if event.kind == "queueState":
            if self._retired.intersection(
                row.input_id for row in event.items + event.restored
            ):
                self._hide(uncertain=True)
                return "reject_resurrection", ()
            self.projection = QueueProjection("available", event.items, event.restored)
            echoes = ()
            decision = "accept"
        else:
            if event.input_id in self._retired:
                return "reject_duplicate_start", ()
            if len(self._retired) >= MAX_TOMBSTONES:
                self._hide(lost=True)
                return "reject_tombstone_bound", ()
            known = next(
                (
                    row
                    for row in self.projection.items + self.projection.restored
                    if row.input_id == event.input_id
                ),
                None,
            )
            if (
                known is not None
                and event.text is not None
                and known.text != event.text
            ):
                self._hide(uncertain=True)
                return "reject_conflicting_start", ()
            self._retired.add(event.input_id)
            self.projection = QueueProjection(
                "available",
                tuple(
                    row
                    for row in self.projection.items
                    if row.input_id != event.input_id
                ),
                tuple(
                    row
                    for row in self.projection.restored
                    if row.input_id != event.input_id
                ),
            )
            echoes = (
                (QueueItem(event.input_id, event.text),)
                if event.text is not None
                else ()
            )
            decision = "accept_exact_id"
        self.revision, self._digest, self._kind = (
            event.revision,
            event.digest,
            event.kind,
        )
        return decision, echoes
