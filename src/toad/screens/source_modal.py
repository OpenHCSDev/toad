"""Rich modals retain their source's project and navigation capabilities."""
from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from metaclass_registry.mro_dispatch import handles
from toad.core_event_carrier import CoreEventMessage, CoreEventReceiver
from toad.navigation_target import SelectTarget
from toad.project_path_owner import ProjectPathOwner
from toad.screens.modal import DismissibleScreen

if TYPE_CHECKING:
    from textual.widget import Widget


class SourceModal(CoreEventReceiver, ProjectPathOwner, DismissibleScreen[None]):
    """Rich modal content keeps the original view's project and navigation."""

    @property
    @abstractmethod
    def source_view(self) -> Widget: ...

    @property
    def project_root(self):
        return ProjectPathOwner.containing(self.source_view).project_root

    @property
    def coordination_root(self):
        return ProjectPathOwner.containing(self.source_view).coordination_root

    @property
    def link_context_events(self):
        return ProjectPathOwner.containing(self.source_view).link_context_events

    @handles(SelectTarget)
    def open_target(self, event: SelectTarget, message: CoreEventMessage) -> None:
        message.stop()
        self.dismiss(None)
        self.source_view.publish_core(event)
