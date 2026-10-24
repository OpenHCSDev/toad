"""Keep queue attachment freshness; queue contents belong to the producer."""

from __future__ import annotations

from agent_comms.acp_extension import (
    IdentifiedInputStarted,
    InputStartedUpdate,
    NoQueueScope,
    PendingQueueProjection,
    QueueChangedUpdate,
    UnavailableQueueProjection,
)

from .projection_attachment import ProjectionAttachment


class QueueAttachment(ProjectionAttachment):
    def __init__(self):
        super().__init__()
        self._last_started: IdentifiedInputStarted | None = None
        self._pending_starts: list[InputStartedUpdate] = []
        # Core's load answer may name why this attachment cannot take input.
        self.unavailable: UnavailableQueueProjection = UnavailableQueueProjection()

    @property
    def scope(self):
        return self.current.scope if self.current is not None else NoQueueScope()

    @property
    def projection(self):
        return self.state.project(
            self.current,
            available=lambda current: current.projection,
            pending=PendingQueueProjection(),
            unavailable=self.unavailable,
        )

    def accepts_request(self, scope) -> bool:
        """A request's original queue authority must still own this attachment."""
        return self.scope.same_request(scope) and scope.accepts_request(self.projection)

    def _acquire_input_scope(self, scope):
        if not self.scope.same_request(scope):
            raise ValueError('The original input attachment changed before capture.')
        return scope.require_live()

    def capture_human_input(self, comms, scope):
        """Certify the original captured request through its current observation."""
        return self.projection.capture_human_input(
            comms, lambda: self._acquire_input_scope(scope))

    def begin(self, session_id):
        self._pending_starts.clear()
        self.unavailable = UnavailableQueueProjection()
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
    ) -> tuple[InputStartedUpdate, ...]:
        return update.queue_started(lambda identified: self._identified_started(identified, session_id))

    def _identified_started(
        self, update: IdentifiedInputStarted, session_id: str,
    ) -> tuple[IdentifiedInputStarted, ...]:
        if not update.scope.matches_session(session_id):
            return ()
        if self._pending:
            self._observe_floor(update.scope)
            if len(self._pending_starts) >= self.MAX_PREBIND:
                self._quarantine(uncertain=True)
            else:
                self._pending_starts.append(update)
            return ()
        if self.quarantined or not self.scope.current_for(update.scope):
            return ()
        previous = self._last_started
        if (
            update.text is None
            or update.revision is None
            or (previous is not None and previous.scope.current_for(update.scope)
                and update.revision <= previous.revision)
        ):
            return ()
        self._last_started = update
        return (update,)
