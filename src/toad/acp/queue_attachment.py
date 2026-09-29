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
        self._started_revision = 0
        self._started_scope = None
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
        if self.scope != scope:
            return False
        return scope is None or self.projection.status == "available"

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
        if self.quarantined or self.scope != update.scope:
            return ()
        if self._started_scope != update.scope:
            self._started_scope = update.scope
            self._started_revision = 0
        if (
            update.input_id is None
            or update.text is None
            or update.revision is None
            or update.revision <= self._started_revision
        ):
            return ()
        self._started_revision = update.revision
        return (QueueItem(update.input_id, update.text),)
