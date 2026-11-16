"""Native Textual application capabilities for the Comms route and observation owners.

Inherits the shared CommsHost contract from toad.client.host; adds Textual-specific
capabilities (ThemedApp, CoreEventReceiver, BusPickerHost) and the fields the
observation layer needs from the native app.
"""

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import Never

from formbridge.operations import OperationKind

from agent_comms.execution.launch_runtime import LaunchRuntime
from agent_comms.projects.checkouts import Checkout

from toad.application_outcome import ApplicationOutcome
from toad.client.bus_selection import BusPickerHost
from toad.client.host import NavigatingHost
from toad.core.events import CoreEventStream
from toad.core_event_carrier import CoreEventReceiver
from toad.textual_colours import ThemedApp
from toad.work_preparation import PreparationRuntime
from textual.timer import Timer


class CommsHost[Source](CoreEventReceiver, BusPickerHost, ThemedApp[ApplicationOutcome], NavigatingHost[Source]):
    """A themed native app publishes Core events and owns its observation resources.

    The shared host contract comes last in the bases, so Textual's own
    copy_to_clipboard and ThemedApp's show_error answer it; the rest are
    Textual primitives here.
    """

    preparation: PreparationRuntime
    events: CoreEventStream
    project_dir: Checkout

    @abstractmethod
    def succeed_onto(self, runtime: LaunchRuntime) -> Never: ...

    def schedule_ui(self, callback: Callable[[], None]) -> None:
        self.call_next(callback)

    def repeat_ui(self, seconds: float, callback: Callable[[], None]) -> Timer:
        return self.set_interval(seconds, callback)

    def run_operation(self, kind: type[OperationKind], task: Callable[[], Awaitable[None]]) -> None:
        self.run_worker(task, group=kind.group, exclusive=kind.exclusive)

    def cancel_operations(self, kind: type[OperationKind]) -> None:
        self.workers.cancel_group(self, kind.group)

    def report_fatal(self, error: Exception) -> None:
        self._handle_exception(error)

    def show_warning(self, text: str, title: str) -> None:
        self.notify(text, title=title, severity="warning")
