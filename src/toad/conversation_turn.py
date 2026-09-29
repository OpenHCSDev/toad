"""Turn permissions and ordered ownership, independent of widget presentation."""
from abc import abstractmethod
from dataclasses import dataclass, replace
from agent_comms.declared_family import DeclaredFamily


class TurnOwner(DeclaredFamily, affix="Turn"):
    managed_id = None
    activity = ""
    started_at = None

    @property
    @abstractmethod
    def busy(self) -> bool: ...

    @property
    def accepts_prompt(self) -> bool:
        return not self.busy

    @property
    def can_compact(self) -> bool:
        return not self.busy

    @property
    @abstractmethod
    def session_state(self) -> str | None: ...

    def matches_settlement(self, turn_id) -> bool:
        return not turn_id

    def with_activity(self, activity: str) -> "TurnOwner":
        return ActivityTurn(activity) if activity else self


@dataclass(frozen=True)
class NoTurn(TurnOwner):
    busy = False
    session_state = None


@dataclass(frozen=True)
class ClientTurn(TurnOwner):
    busy = False
    session_state = "idle"


@dataclass(frozen=True)
class ActivityTurn(TurnOwner):
    """A local operation owns its visible activity until it finishes."""
    activity: str
    busy = True
    session_state = "busy"

    def with_activity(self, activity: str) -> TurnOwner:
        return replace(self, activity=activity) if activity else ClientTurn()


@dataclass(frozen=True)
class AgentTurn(TurnOwner):
    managed_id: str | None = None
    activity: str = "Thinking…"
    started_at: float | None = None
    busy = True
    session_state = "busy"

    def matches_settlement(self, turn_id) -> bool:
        return self.managed_id == turn_id

    def with_activity(self, activity: str) -> "AgentTurn":
        return replace(self, activity=activity or "Thinking…")


class TurnBinding(DeclaredFamily, affix="TurnBinding"):
    """An agent's presentation declares where its turn authority lives."""

    @property
    @abstractmethod
    def owner(self) -> TurnOwner: ...

    @abstractmethod
    def accepts(self, message) -> bool: ...

    @abstractmethod
    def start(self, update) -> bool: ...

    @abstractmethod
    def settle(self, update) -> bool: ...

    @abstractmethod
    def describe(self, activity: str) -> None: ...

    def start_client(self) -> None:
        """Managed requests wait for their agent's authoritative receipt."""

    def finish_client(self) -> None:
        """A local request cannot settle a managed turn."""


class LocalTurnBinding(TurnBinding):
    def __init__(self, agent=None):
        self._owner = NoTurn()

    @property
    def owner(self) -> TurnOwner:
        return self._owner

    def accepts(self, message) -> bool:
        return message.agent is None

    def start(self, update) -> bool:
        owner = AgentTurn(update.turn_id, update.activity_detail or "Thinking…", update.started_at)
        if owner == self._owner:
            return False
        self._owner = owner
        return True

    def settle(self, update) -> bool:
        if not self._owner.matches_settlement(update.turn_id):
            return False
        self.finish_client()
        return True

    def describe(self, activity: str) -> None:
        self._owner = self._owner.with_activity(activity)

    def start_client(self) -> None:
        self._owner = AgentTurn()

    def finish_client(self) -> None:
        self._owner = ClientTurn()


class ManagedTurnBinding(TurnBinding):
    def __init__(self, agent):
        self.agent = agent

    @property
    def owner(self) -> TurnOwner:
        return self.agent.current_turn

    def accepts(self, message) -> bool:
        return (message.agent is self.agent and message.session_id == self.agent.session_id
                and message.sequence > 0)

    def start(self, update) -> bool:
        return self.owner.busy and self.owner.matches_settlement(update.turn_id)

    def settle(self, update) -> bool:
        return not self.owner.busy

    def describe(self, activity: str) -> None:
        if self.owner.busy:
            self.agent.describe_turn(activity)


class ConversationTurn:
    """Stable widget binding; managed turn values stay solely on the agent."""
    def __init__(self, changed):
        self._binding = LocalTurnBinding()
        self._changed = changed
        self._source = None
        self._sequence = 0

    @property
    def owner(self) -> TurnOwner:
        return self._binding.owner

    def bind(self, agent) -> None:
        self._binding = agent.presentation.turns if agent is not None else LocalTurnBinding()
        self._source = None
        self._sequence = 0
        self._changed(self.owner)

    @property
    def managed_id(self) -> str | None:
        return self.owner.managed_id

    def accept(self, message) -> bool:
        if not self._binding.accepts(message):
            return False
        if message.agent is None:
            return True
        source = (message.agent, message.session_id)
        if source == self._source and message.sequence <= self._sequence:
            return False
        self._source, self._sequence = source, message.sequence
        return True

    def start(self, message) -> bool:
        if not self.accept(message) or not self._binding.start(message.update):
            return False
        self._changed(self.owner)
        return True

    def settle(self, message) -> bool:
        if not self.accept(message) or not self._binding.settle(message.update):
            return False
        self._changed(self.owner)
        return True

    def describe(self, activity: str) -> None:
        self._binding.describe(activity)
        self._changed(self.owner)

    def start_client(self) -> None:
        self._binding.start_client()
        self._changed(self.owner)

    def finish_client(self) -> None:
        self._binding.finish_client()
        self._changed(self.owner)
