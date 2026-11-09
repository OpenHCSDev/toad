"""Native application capabilities used by the Comms route and observation owners."""

from abc import abstractmethod
from typing import Never

from agent_comms.execution.launch_runtime import LaunchRuntime
from agent_comms.projects.checkouts import Checkout

from toad.application_outcome import ApplicationOutcome
from toad.bus_selection import BusPickerHost
from toad.core.events import CoreEventStream
from toad.core_event_carrier import CoreEventReceiver
from toad.session_projection import SessionCollection
from toad.tab_order import TabOrder
from toad.textual_colours import ThemedApp
from toad.work_preparation import PreparationRuntime


class CommsHost[Source](CoreEventReceiver, BusPickerHost, ThemedApp[ApplicationOutcome]):
    """A themed native app publishes Core events and owns its observation resources."""

    preparation: PreparationRuntime
    events: CoreEventStream
    project_dir: Checkout
    tab_order: TabOrder
    session_navigation: SessionCollection[Source]

    @abstractmethod
    def succeed_onto(self, runtime: LaunchRuntime) -> Never: ...
