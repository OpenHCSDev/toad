"""A viewed object's state and its two presentations, inherited by files and conversations."""
from functools import cached_property
from metaclass_registry.mro_dispatch import handles
from textual import events, on, work
from textual.geometry import Region
from textual.widgets import Static
from toad.core.events import ConfigurationChanged
from toad.core_event_carrier import CoreEventReceiver
from toad.forms.object_configuration import ObjectFieldView, ObjectFormView
from toad.native_style import FillHeight
from toad.screens.modal import DismissibleScreen, ModalPanel
from toad.forms.presentation import FormModal
from toad.client.session_tracker import SidebarState
from toad.client.sidebar_panels import ActionPropertiesPanel, ObjectPropertiesPanel
from toad.settings_scope import ViewSettingsScope
from toad.widgets.acting_button import DismissButton
from toad.widgets.comms_command_dialog import CommandForm
from toad.widgets.comms_menu import ActionMenu
from toad.widgets.model_switcher import SessionForm
from toad.widgets.side_bar import (
    PanelMenu,
    SideBar,
    SidebarPanelWidget,
    ThreadSidebar,
)





class FormSidebarPanel(FillHeight, SidebarPanelWidget):
    """A sidebar panel backed by a form whose pending edits finish with the panel."""

    def finish(self):
        self.form.finish()


class ObjectProperties(ObjectPropertiesPanel, FormSidebarPanel):
    """One declared settings entry; its form is built when that entry is opened."""

    def __init__(self, field):
        super().__init__()
        self.field = field

    def compose(self):
        self.form = ObjectFormView(self.field.state, [ObjectFieldView.from_field(self.field)])
        yield self.form


class AgentProperties(CoreEventReceiver, FormSidebarPanel):
    """The selected native session's advertisements, using its original writer."""

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.listen(events.Mount, self.follow_binding)

    @classmethod
    def panel(cls, view):
        return SideBar.Panel(title="Session settings", widget=cls(view), id="agent-settings", flex=True)

    def compose(self):
        self.form = SessionForm.for_prompt(self.view.conversation.prompt)
        if not self.form.values:
            yield Static("This session has not advertised any settings.", markup=False)
        yield self.form

    def follow_binding(self):
        self.watch(self.view.conversation, "agent_binding", self.binding_changed)

    def binding_changed(self, old, new):
        self.retire_core_observations(old.events)
        self.observe_core(new.events)
        self.configuration_changed()

    @handles(ConfigurationChanged)
    def configuration_changed(self):
        if self.is_mounted:
            self.rebuild_form()

    @work(exclusive=True, group="agent-settings")
    async def rebuild_form(self):
        await self.recompose()


class ActionProperties(ActionPropertiesPanel, CommandForm, SidebarPanelWidget):
    """The original backend operation form, using its original target writer."""

    def __init__(self, context, definition, fields):
        self.context = context
        super().__init__(definition, context.title, fields, context.observed.core)


class ObjectConfigurationDialog(FormModal[None], DismissibleScreen[None]):
    def __init__(self, view):
        super().__init__()
        self.form = PanelMenu(view.configuration_panels, SidebarState(), view)

    def compose(self):
        with ModalPanel():
            yield self.form
            yield DismissButton("Done")

    def dismiss_control(self):
        self.form.finish()
        super().dismiss_control()


class ConfiguredView(ViewSettingsScope):
    footer_compact = True

    @property
    def configuration_mode(self):
        return self.id

    @property
    def configuration_panels(self):
        for field in self.configuration_fields():
            panel = self.field_panel(field)
            yield SideBar.Panel(title=panel.title, widget=ObjectProperties(field),
                                id=panel.id, flex=panel.flex)

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
        self.app.push_screen(ObjectConfigurationDialog(self))
