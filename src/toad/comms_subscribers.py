"""Callbacks implemented by native views that subscribe to Core observations."""

from abc import abstractmethod
from collections.abc import Mapping

from agent_comms.messaging.message_notification import MessageNotification
from textual.abstract_hooks import AbstractHooksMeta


class SidebarSubscriber[Source, Failure](metaclass=AbstractHooksMeta):
    """A sidebar view accepts a source, its opening failure and later row changes."""

    @abstractmethod
    def bind_observation(self, observed: Source) -> None: ...

    @abstractmethod
    def bind_failed_observation(self, observed: Failure) -> None: ...

    @abstractmethod
    def present(self, **changes: object) -> None: ...


class NotificationSubscriber(metaclass=AbstractHooksMeta):
    """A message view receives notification outcomes for its current read scope."""

    @abstractmethod
    def notifications_observed(
        self,
        outcomes: Mapping[tuple[int, str], tuple[MessageNotification, ...]],
    ) -> None: ...

    @abstractmethod
    def notifications_failed(self, error: Exception) -> None: ...

    @abstractmethod
    def notifications_reload(self) -> None: ...
