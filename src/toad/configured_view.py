"""A viewed object's state and its two presentations, inherited by files and conversations."""
from functools import cached_property
from textual import events, on
from textual.geometry import Region
from toad.forms.object_configuration import ObjectFormView
from toad.object_configuration import ObjectConfiguration
from toad.screens.modal import DismissibleScreen, ModalPanel
from toad.forms.presentation import FormModal
from toad.session_tracker import SidebarState
from toad.settings_scope import ViewSettingsScope
from toad.widgets.acting_button import DismissButton
from toad.widgets.comms_menu import ActionMenu
from toad.widgets.side_bar import (
    SideBar,
    SidebarPanelWidget,
    ThreadSidebar,
)





class ObjectProperties(ObjectFormView, SidebarPanelWidget):
    """The sidebar edits the view's original state directly."""


class ObjectConfigurationDialog(FormModal[None], DismissibleScreen[None]):
    def __init__(self, state):
        super().__init__()
        self.form = ObjectFormView.whole(state)

    def compose(self):
        with ModalPanel():
            yield self.form
            yield DismissButton("Done")

    def dismiss_control(self):
        self.form.finish()
        super().dismiss_control()


class ConfiguredView(ViewSettingsScope):
    @cached_property
    def configuration_state(self) -> ObjectConfiguration:
        identity = self.app.session_navigation.get(self.id).identity
        return ObjectConfiguration(identity, self.app.saved_settings.state,
                                   self.app.saved_settings.path().parent, self)

    @property
    def configuration_panel(self):
        return SideBar.Panel("Properties", ObjectProperties.whole(self.configuration_state),
                             flex=True, collapsed=True)

    def make_thread_sidebar(self):
        return ThreadSidebar(state=SidebarState())

    @cached_property
    def thread_sidebar(self):
        return self.make_thread_sidebar()

    def sidebars(self):
        return (self.thread_sidebar,)

    @on(events.Unmount)
    def close_configuration(self):
        self.configuration_state.close()

    @on(events.Click)
    def configuration_menu(self, event):
        if event.button != 3:
            return
        event.stop()
        event.prevent_default()
        # The properties form is shared; opening it never copies the state's values.
        ActionMenu.show(self.screen, Region.from_offset(event.screen_offset, (0, 0)),
                        self.display_name, [(self.open_configuration, "Properties…")])

    def open_configuration(self):
        self.app.push_screen(ObjectConfigurationDialog(self.configuration_state))
