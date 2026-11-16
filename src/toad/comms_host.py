"""Native Textual application capabilities for the Comms route and observation owners.

Inherits the shared CommsHost contract from toad.client.host; adds Textual-specific
capabilities (ThemedApp, CoreEventReceiver, BusPickerHost) and the fields the
observation layer needs from the native app.
"""

from abc import abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Never

from agent_comms.execution.launch_runtime import LaunchRuntime
from agent_comms.history_views import RetiredViews
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.projects.checkouts import Checkout

from toad.application_outcome import ApplicationOutcome
from toad.client.bus_selection import BusPickerHost
from toad.client.host import CommsHost as SharedCommsHost
from toad.core.events import CoreEventStream
from toad.core_event_carrier import CoreEventReceiver
from toad.client.session_projection import SessionCollection
from toad.client.tab_order import TabOrder
from toad.textual_colours import ThemedApp
from toad.work_preparation import PreparationRuntime
from textual.timer import Timer


class CommsHost[Source](CoreEventReceiver, BusPickerHost, ThemedApp[ApplicationOutcome], SharedCommsHost):
    """A themed native app publishes Core events and owns its observation resources.

    The shared host contract comes last in the bases, so Textual's own
    copy_to_clipboard and ThemedApp's show_error answer it; the rest are
    Textual primitives here.
    """

    preparation: PreparationRuntime
    events: CoreEventStream
    project_dir: Checkout
    tab_order: TabOrder
    session_navigation: SessionCollection[Source]

    @abstractmethod
    def succeed_onto(self, runtime: LaunchRuntime) -> Never: ...

    def schedule_ui(self, callback: Callable[[], None]) -> None:
        self.call_next(callback)

    def repeat_ui(self, seconds: float, callback: Callable[[], None]) -> Timer:
        return self.set_interval(seconds, callback)

    def report_fatal(self, error: Exception) -> None:
        self._handle_exception(error)

    def show_warning(self, text: str, title: str) -> None:
        self.notify(text, title=title, severity="warning")

    @property
    def tab_names(self) -> tuple[str, ...]:
        return self.tab_order.names

    def open_thread_identities(self, root: str) -> set[ThreadIncarnation]:
        return {identity for member in self.session_navigation.members
                for owner, identity in member.original_threads(self.session_navigation)
                if owner == root}

    def open_channel_targets(self, root: str) -> set[str]:
        return {target for member in self.session_navigation.members
                for owner, target in member.original_channels() if owner == root}

    def retire_views(self, root: Path, retired: RetiredViews) -> None:
        self.session_navigation.views_retired(root, retired)
