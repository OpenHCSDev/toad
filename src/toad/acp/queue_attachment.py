"""Keep queue attachment freshness; queue contents belong to the producer."""

from __future__ import annotations

from agent_comms.acp_extension import (
    InputStartedUpdate,
    PendingQueueProjection,
    QueueChangedUpdate,
    QueueItem,
    UnavailableQueueProjection,
)

from .projection_attachment import ProjectionAttachment


class QueueAttachment(ProjectionAttachment):
    def __init__(self):
        super().__init__()
        self._last_started: InputStartedUpdate | None = None
        self._pending_starts: list[InputStartedUpdate] = []

    @property
    def scope(self):
        return self.current.scope if self.current is not None else None

    @property
    def projection(self):
        if self.status == "available" and self.current is not None:
            return self.current.projection
        return (
            PendingQueueProjection()
            if self.status is None
            else UnavailableQueueProjection()
        )

    def accepts_request(self, scope) -> bool:
        """A request's original queue authority must still own this attachment."""
        if scope is None:
            return self.scope is None
        return (self.scope is not None and self.scope.relation(scope).current
                and self.projection.status == "available")

    def begin(self, session_id):
        self._pending_starts.clear()
        return super().begin(session_id)

    def bind(self, value: QueueChangedUpdate, session_id: str, token: int):
        result = super().bind(value, session_id, token)
        pending, self._pending_starts = self._pending_starts, []
        starts = tuple(
            item for fact in pending for item in self.started(fact, session_id)
        )
        return result, starts

    def started(
        self, update: InputStartedUpdate, session_id: str
    ) -> tuple[QueueItem, ...]:
        if update.scope is None or update.scope.session_id != session_id:
            return ()
        if self._pending:
            self._observe_floor(update.scope)
            if len(self._pending_starts) >= self.MAX_PREBIND:
                self._quarantine(uncertain=True)
            else:
                self._pending_starts.append(update)
            return ()
        if (self.quarantined or self.scope is None
                or not self.scope.relation(update.scope).current):
            return ()
        previous = self._last_started
        if (
            update.input_id is None
            or update.text is None
            or update.revision is None
            or (previous is not None and previous.scope.relation(update.scope).current
                and update.revision <= previous.revision)
        ):
            return ()
        self._last_started = update
        return (QueueItem(update.input_id, update.text),)
