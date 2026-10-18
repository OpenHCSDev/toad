"""Local ACP turns and source-fenced projections of the backend's turn owner."""
from abc import abstractmethod
from dataclasses import dataclass, replace

from agent_comms.activity import ActivityState
from agent_comms.declared_family import DeclaredFamily
from agent_comms.turn_lease import TurnState
from agent_comms.ui_model.status import ThreadStatusModel


class TurnOwner(DeclaredFamily, affix="Turn"):
    managed_id = None
    activity = ""
    started_at = None
    activity_state = ActivityState.IDLE

    @property
    def presentation_status(self):
        return self.activity_state.presentation_status

    @property
    def busy(self) -> bool:
        return self.activity_state.busy

    @property
    def status(self) -> str:
        """The local request's visible state, independent of observed thread status."""
        return " ".join(self.activity.splitlines()) if self.busy else "Ready"

    @property
    def accepts_prompt(self) -> bool:
        return not self.busy

    @property
    def can_compact(self) -> bool:
        return not self.busy

    @property
    def can_cancel(self) -> bool:
        return self.busy

    @property
    @abstractmethod
    def session_state(self) -> str | None: ...

    def matches_settlement(self, turn_id) -> bool:
        return not turn_id

    def captured_snapshot(self, widgets):
        """Each original claim owns capture while this source is active."""
        from toad.widgets.committed_presentation import CommitParticipant

        return frozenset(widget for widget in widgets
                         if not isinstance(widget, CommitParticipant)
                         or widget.commit_claim.capture(not self.busy))

    def with_activity(self, activity: str) -> "TurnOwner":
        return ActivityTurn(activity) if activity else self

    def response_stream(self, delivery):
        from toad.live_output import CompleteResponseStream
        return CompleteResponseStream(delivery)


@dataclass(frozen=True)
class NoTurn(TurnOwner):
    session_state = None


@dataclass(frozen=True)
class ClientTurn(TurnOwner):
    session_state = "idle"


@dataclass(frozen=True)
class ActivityTurn(TurnOwner):
    activity: str
    activity_state = ActivityState.WORKING
    session_state = "busy"

    def with_activity(self, activity: str) -> TurnOwner:
        return replace(self, activity=activity) if activity else ClientTurn()


@dataclass(frozen=True)
class AgentTurn(TurnOwner):
    """A generic ACP peer owns its local request, but cannot control Comms turns."""
    managed_id: str | None = None
    activity: str = "Thinking…"
    started_at: float | None = None
    activity_state = ActivityState.WORKING
    session_state = "busy"

    def matches_settlement(self, turn_id) -> bool:
        return self.managed_id == turn_id

    def with_activity(self, activity: str) -> TurnOwner:
        return replace(self, activity=activity or "Thinking…")

    def response_stream(self, delivery):
        from toad.live_output import ResponseStream
        return ResponseStream(delivery, turn_id=self.managed_id)


@dataclass(frozen=True)
class ManagedTurn(TurnOwner):
    """The published lease owns phase, permissions, activity and identity."""
    state: TurnState = TurnState()

    @property
    def busy(self):
        return self.state.active.phase.busy

    @property
    def activity_state(self):
        return self.state.active.phase.activity_state

    @property
    def managed_id(self):
        return self.state.active.id

    @property
    def accepts_prompt(self):
        return self.state.active.phase.accepts_prompt

    @property
    def can_compact(self):
        return self.state.active.phase.can_compact

    @property
    def can_cancel(self):
        return self.state.active.phase.can_cancel

    @property
    def activity(self):
        return self.state.active.phase.summary if self.busy else ""

    @property
    def started_at(self):
        return self.state.active.started_at

    @property
    def session_state(self):
        return "busy" if self.busy else "idle"

    def matches_settlement(self, turn_id):
        return self.state.matches(turn_id)

    def with_activity(self, activity):
        # Text, tool and heartbeat rendering cannot change backend phase.
        return self

    def response_stream(self, delivery):
        if self.busy:
            from toad.live_output import ResponseStream
            return ResponseStream(delivery, turn_id=self.managed_id)
        return super().response_stream(delivery)


class TurnBinding(DeclaredFamily, affix="TurnBinding"):
    managed = False
    sequence = 0

    @property
    @abstractmethod
    def owner(self) -> TurnOwner: ...

    @abstractmethod
    def status_row(self, observed: ThreadStatusModel) -> ThreadStatusModel: ...

    @abstractmethod
    def accepts(self, message) -> bool: ...

    @abstractmethod
    def describe(self, activity: str) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...

    async def present_input(self, view, text) -> None:
        """Display managed inputs only when the native process reports they started."""

    def start_client(self) -> None:
        """A managed request waits for its authoritative owner publication."""

    def finish_client(self) -> None:
        """A local RPC result cannot settle a managed turn."""


class LocalTurnBinding(TurnBinding):
    def __init__(self, agent=None):
        self._owner = NoTurn()

    @property
    def owner(self):
        return self._owner

    def status_row(self, observed):
        owner = self.owner
        return ThreadStatusModel.known("", owner.activity_state.presentation("", owner.activity))

    def accepts(self, message):
        """A local turn cannot accept a backend-owned managed publication."""
        return False

    def describe(self, activity):
        self._owner = self._owner.with_activity(activity)

    def reset(self):
        self._owner = NoTurn()

    async def present_input(self, view, text):
        from toad.widgets.user_input import UserInput
        await view.post(UserInput(text))

    def start_client(self):
        self._owner = AgentTurn()

    def finish_client(self):
        self._owner = ClientTurn()


class ManagedTurnBinding(TurnBinding):
    managed = True

    def __init__(self, agent):
        self.agent = agent
        self._owner = ManagedTurn()
        self.sequence = 0

    @property
    def owner(self):
        return self._owner

    def status_row(self, observed):
        return observed

    def accepts(self, message):
        return (message.publisher is self.agent and message.event.session_id == self.agent.session_id
                and message.event.sequence == self.sequence)

    def receive(self, state: TurnState):
        if not state.busy and not state.matches(self.owner.managed_id):
            return False
        owner = ManagedTurn(state)
        if owner == self.owner:
            return False
        self._owner = owner
        self.sequence += 1
        return True

    def describe(self, activity):
        """Only the backend publication changes a managed phase."""

    def reset(self):
        self._owner = ManagedTurn()
        self.sequence += 1


class ConversationTurn:
    """Read the actual source binding; the widget keeps no managed state or cursor."""
    def __init__(self, changed, source):
        self._local = LocalTurnBinding()
        self._source = source
        self._changed = changed

    @property
    def binding(self):
        return self._source() or self._local

    @property
    def owner(self):
        return self.binding.owner

    def bound(self):
        self._changed(self.owner)

    @property
    def managed_id(self):
        return self.owner.managed_id

    def changed(self, message):
        before = self.owner
        if not self.binding.accepts(message):
            return False
        self._notify(before)
        return True

    def describe(self, activity):
        before = self.owner
        self.binding.describe(activity)
        self._notify(before)

    def _notify(self, before):
        # Streaming describes the turn on every chunk and publications repeat
        # unchanged leases; consumers re-sync prompt, footer bindings and
        # details, so they hear only an actual change of owner.
        if (owner := self.owner) != before:
            self._changed(owner)

    def start_client(self):
        self.binding.start_client()
        self._changed(self.owner)

    def finish_client(self):
        self.binding.finish_client()
        self._changed(self.owner)
