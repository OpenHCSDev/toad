"""Native Textual application capabilities for the Comms route and observation owners.

Inherits the shared CommsHost contract from toad.client.host; adds Textual-specific
capabilities (ThemedApp, CoreEventReceiver, BusPickerHost) and the fields the
observation layer needs from the native app.
"""

from abc import abstractmethod
from typing import Never

from agent_comms.execution.launch_runtime import LaunchRuntime
from agent_comms.projects.checkouts import Checkout

from toad.application_outcome import ApplicationOutcome
from toad.bus_selection import BusPickerHost
from toad.client.host import CommsHost as SharedCommsHost
from toad.core.events import CoreEventStream
from toad.core_event_carrier import CoreEventReceiver
from toad.session_projection import SessionCollection
from toad.tab_order import TabOrder
from toad.textual_colours import ThemedApp
from toad.work_preparation import PreparationRuntime


class CommsHost[Source](SharedCommsHost, CoreEventReceiver, BusPickerHost, ThemedApp[ApplicationOutcome]):
    """A themed native app publishes Core events and owns its observation resources.

    Inherits the shared host contract (schedule_ui, repeat_ui, report_fatal,
    show_warning, show_error, copy_to_clipboard, running_loop, project_dir).
    The concrete ToadApp implements them through Textual's primitives.
    """

    preparation: PreparationRuntime
    events: CoreEventStream
    project_dir: Checkout
    tab_order: TabOrder
    session_navigation: SessionCollection[Source]

    @abstractmethod
    def succeed_onto(self, runtime: LaunchRuntime) -> Never: ...
