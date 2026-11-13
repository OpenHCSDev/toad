"""A viewed object's state and its two presentations, inherited by files and conversations."""
from functools import cached_property
from textual import events, on
from textual.geometry import Region
from toad.forms.object_configuration import ObjectFieldView, ObjectFormView
from toad.native_style import FillHeight
from toad.object_configuration import ObjectConfiguration
from toad.screens.modal import DismissibleScreen, ModalPanel
from toad.forms.presentation import FormModal
from toad.session_tracker import SidebarState
from toad.settings_scope import ViewSettingsScope
from toad.widgets.acting_button import DismissButton
from toad.widgets.comms_menu import ActionMenu
from toad.widgets.side_bar import (
    PanelMenu,
    SideBar,
    SidebarPanelWidget,
    ThreadSidebar,
)





class ObjectProperties(FillHeight, SidebarPanelWidget):
    """One declared settings entry; its form is built when that entry is opened."""

    def __init__(self, field):
        super().__init__()
        self.field = field

    @property
    def panel_identity(self):
        return self.field.path

    def compose(self):
        self.form = ObjectFormView(self.field.state, [ObjectFieldView.from_field(self.field)])
        yield self.form

    def finish(self):
        self.form.finish()


class ObjectConfigurationDialog(FormModal[None], DismissibleScreen[None]):
    def __init__(self, panels):
        super().__init__()
        self.form = PanelMenu(panels, SidebarState())

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
    def configuration_panels(self):
        state = self.configuration_state
        for path in state.direct_parameter_paths():
            if state.shows(path.value):
                field = state.field(path.value)
                yield SideBar.Panel(field.label, ObjectProperties(field),
                                    id=f"settings-{path.value}", flex=True)

    @cached_property
    def _thread_sidebar_state(self):
        return SidebarState()

    def make_thread_sidebar(self):
        return ThreadSidebar(state=self._thread_sidebar_state)

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
        self.app.push_screen(ObjectConfigurationDialog(self.configuration_panels))
