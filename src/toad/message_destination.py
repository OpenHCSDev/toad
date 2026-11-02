"""A retained message destination, independent of its conversation widgets."""
from __future__ import annotations

from abc import ABC, abstractmethod

from agent_comms.channel_targets import NamedTarget
from agent_comms.comms import Comms


class MessageDestination(ABC):
    @abstractmethod
    def retained_target(self) -> NamedTarget: ...

    def send_target(self) -> NamedTarget:
        return self.retained_target()

    def read_only(self, comms: Comms) -> bool:
        return False
