"""A source that can attach an explicit session-load plan to its retained view."""

from abc import ABC, abstractmethod

from agent_comms.session_load import ExistingSessionLoadPlan


class SessionStartTarget(ABC):
    @abstractmethod
    def attach_started(self, plan: ExistingSessionLoadPlan) -> None: ...
