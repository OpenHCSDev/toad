"""Turn permissions and ordered ownership, independent of widget presentation."""
from abc import abstractmethod
from dataclasses import dataclass
from agent_comms.declared_family import DeclaredFamily


class TurnOwner(DeclaredFamily, affix="Turn"):
    managed_id = None

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


class NoTurn(TurnOwner):
    busy = False
    session_state = None


class ClientTurn(TurnOwner):
    busy = False
    session_state = "idle"


@dataclass(frozen=True)
class AgentTurn(TurnOwner):
    managed_id: str | None = None
    busy = True
    session_state = "busy"

    def matches_settlement(self, turn_id) -> bool:
        return self.managed_id == turn_id


class ConversationTurn:
    """Own the current turn and the immutable ingress order that can change it."""
    def __init__(self, changed):
        self._owner = NoTurn()
        self._changed = changed
        self._source = None
        self._sequence = 0

    @property
    def owner(self) -> TurnOwner:
        return self._owner

    @owner.setter
    def owner(self, owner: TurnOwner) -> None:
        self._owner = owner
        self._changed(owner)

    @property
    def managed_id(self) -> str | None:
        return self.owner.managed_id

    def accept(self, message, agent) -> bool:
        # One ingress boundary: local agents do not publish managed turns.
        if (agent is None or not agent.presentation.uses_managed_turns) and message.agent is None:
            return True
        if (message.agent is not agent or message.session_id != agent.session_id
                or message.sequence <= 0):
            return False
        source = (message.agent, message.session_id)
        if source == self._source and message.sequence <= self._sequence:
            return False
        self._source, self._sequence = source, message.sequence
        return True

    def start(self, message, agent) -> TurnOwner | None:
        if not self.accept(message, agent) or message.update.turn_id == self.managed_id:
            return None
        previous = self.owner
        self.owner = AgentTurn(message.update.turn_id)
        return previous

    def settle(self, message, agent) -> TurnOwner | None:
        if not self.accept(message, agent) or not self.owner.matches_settlement(message.update.turn_id):
            return None
        previous = self.owner
        self.owner = ClientTurn()
        return previous
