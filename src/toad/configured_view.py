"""A viewed object's state and its two presentations, inherited by files and conversations."""
from functools import cached_property
from agent_comms.registry.agent_settings_wire import AgentSettingsScope
from metaclass_registry.mro_dispatch import handles
from textual import containers, events, on, work
from textual._callback import invoke
from textual.geometry import Region
from textual.widgets import OptionList, Select, Static
from toad.client.agent_settings_state import (
    AgentScopeState,
    AgentSettingsPanel,
)
from toad.core.events import ConfigurationChanged
from toad.core_event_carrier import CoreEventReceiver
from toad.forms.object_configuration import ObjectFieldView, ObjectFormView
from toad.native_style import FillHeight
from toad.screens.modal import DismissibleScreen, ModalPanel
from toad.forms.presentation import FormModal
from toad.client.session_tracker import SidebarState
from toad.client.sidebar_panels import ActionPropertiesPanel, ObjectPropertiesPanel, ViewActionsPanel
from toad.settings_scope import ViewSettingsScope
from toad.widgets.acting_button import DismissButton
from toad.widgets.comms_command_dialog import CommandForm
from toad.widgets.comms_menu import ActionMenu, ContextMenuItem
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


class ViewActions(ViewActionsPanel, FillHeight, SidebarPanelWidget):
    """The viewed object's right-click options inside the view settings bar, rendering the
    exact `MenuEntry` list from `ViewSettingsOwner.view_menu_entries`."""

    def __init__(self, view) -> None:
        super().__init__()
        self.view = view
        self._options = OptionList()

    def compose(self):
        yield self._options

    @on(events.Mount)
    def load_actions(self) -> None:
        self.run_worker(self._refresh(), group="view-actions", exclusive=True)

    async def _refresh(self) -> None:
        entries = await self.view.view_menu_entries()
        if not self.is_mounted:
            return
        self._options.clear_options()
        self._options.add_options(ContextMenuItem(entry.run, entry.label) for entry in entries)

    @on(OptionList.OptionSelected)
    async def option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        action = event.option.action  # type: ignore[attr-defined]
        if action is not None:
            await invoke(action)


class AgentSettingsProperties(AgentSettingsPanel, FillHeight, SidebarPanelWidget):
    """Scoped Core agent settings (Global -> Project -> [Channel] -> Thread) over ObjectFormView."""

    def __init__(self, view) -> None:
        super().__init__()
        self.init_agent_settings(view.app, view)
        self._form: ObjectFormView | None = None
        self._scope_select: Select[AgentSettingsScope] = Select(
            (), allow_blank=True, compact=True
        )
        self._scope_select.display = False
        self._status = Static("Loading agent settings…", markup=False)
        self._form_host = containers.Vertical()
        self._form_host.display = False

    def compose(self):
        yield self._scope_select
        yield self._status
        yield self._form_host

    @on(events.Mount)
    def start_load(self) -> None:
        self.run_worker(self.load_agent_settings(), group="agent-settings-load", exclusive=True)

    @on(events.Unmount)
    def stop_agent_settings(self) -> None:
        self.workers.cancel_group(self, "agent-settings-load")
        self.workers.cancel_group(self, "agent-settings-form")
        self.workers.cancel_group(self, "agent-settings-save")
        self.close_agent_settings_chain()

    @on(Select.Changed)
    def scope_selected(self, event: Select.Changed) -> None:
        if event.select is self._scope_select and event.value is not Select.NULL:
            event.stop()
            self.select_agent_scope(event.value)

    def finish(self) -> None:
        self.finish_active_form()

    def settings_panel_alive(self) -> bool:
        return self.is_mounted

    async def run_settings_thread(self, work_fn):
        return await self._settings_app.preparation.run_thread(work_fn)

    def schedule_settings_persist(self, coro) -> None:
        self.run_worker(coro, group="agent-settings-save", exclusive=False)

    def finish_active_form(self) -> None:
        if self._form is not None and self._form.is_mounted:
            self._form.finish()

    def show_loading(self) -> None:
        self._scope_select.display = False
        self._form_host.display = False
        self._status.update("Loading agent settings…")
        self._status.display = True

    def show_unavailable(self, text: str) -> None:
        self._scope_select.display = False
        self._form_host.display = False
        self._status.update(text)
        self._status.display = True

    def show_agent_settings_chain(
        self,
        scopes: tuple[AgentSettingsScope, ...],
        selected: AgentSettingsScope,
        state: AgentScopeState,
    ) -> None:
        with self.prevent(Select.Changed):
            self._scope_select.set_options([(item.label, item) for item in scopes])
            self._scope_select.value = selected
        self._scope_select.display = len(scopes) > 1
        self._status.display = False
        self._form_host.display = True
        self.show_agent_scope_form(state)

    def show_agent_scope_form(self, state: AgentScopeState) -> None:
        self.run_worker(
            self._mount_scope_form(state),
            group="agent-settings-form",
            exclusive=True,
        )

    async def _mount_scope_form(self, state: AgentScopeState) -> None:
        if not self.is_mounted:
            return
        await self._form_host.remove_children()
        self._form = ObjectFormView.whole(state)
        await self._form_host.mount(self._form)


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
    def action_panels(self):
        panel = ViewActionsPanel.panel_spec
        return (SideBar.Panel(title=panel.title, widget=ViewActions(self), id=panel.id, flex=panel.flex),)

    @property
    def agent_settings_panels(self):
        panel = AgentSettingsPanel.panel_spec
        return (
            SideBar.Panel(
                title=panel.title,
                widget=AgentSettingsProperties(self),
                id=panel.id,
                flex=panel.flex,
            ),
        )

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
