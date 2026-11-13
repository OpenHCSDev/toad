import json
from pathlib import Path
root=Path.cwd(); ops=[]
def patch(f,t,o,n): ops.append(dict(operation='patch_target',file_path=str(root/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def insert(f,t,s): ops.append(dict(operation='insert_before_target',file_path=str(root/f),target_qualname=t,source=s))
def imp(f,s): ops.append(dict(operation='ensure_import',file_path=str(root/f),import_source=s))
f='src/toad/widgets/side_bar.py'
insert(f,'ThreadSidebar','''class PanelPage(FillHeight, containers.Vertical):
    """The original panel and its controls, retained while another entry is selected."""


class PanelPicker(OneRow, FillWidth, widgets.Select):
    """One compact selector over the entries supplied by the viewed object."""


class PanelMenu(FillHeight, containers.Vertical):
    """Discover once from the owner; mount each original panel only when selected."""

    def __init__(self, entries, navigation: SidebarState):
        super().__init__()
        self.entries = tuple(entries)
        self.navigation = navigation
        selected = next((entry for entry in self.entries
                         if entry.title == navigation.panel_title), self.entries[0])
        self.picker = PanelPicker(((entry.title, entry) for entry in self.entries),
                                 value=selected, allow_blank=False, compact=True)
        self.body = PanelPage()
        self.pages: dict[SideBar.Panel, PanelPage] = {}

    def compose(self):
        yield self.picker
        yield self.body

    @on(events.Mount)
    async def open_selection(self):
        await self.show_panel(self.picker.value)

    @on(widgets.Select.Changed)
    async def selection_changed(self, event):
        if event.select is self.picker and event.value is not widgets.Select.NULL:
            event.stop()
            await self.show_panel(event.value)

    async def show_panel(self, entry):
        for panel, page in self.pages.items():
            if page.display and panel is not entry:
                panel.widget.finish()
            page.display = panel is entry
            panel.widget.sidebar_visibility_changed()
        if entry not in self.pages:
            children = (() if entry.header_control is None else (entry.header_control,))
            page = PanelPage(*children, entry.widget, id=entry.id)
            self.pages[entry] = page
            await self.body.mount(page)
        self.navigation.panel_title = entry.title
        entry.widget.sidebar_visibility_changed()

    def activate(self, widget):
        self.picker.value = next(entry for entry in self.entries if entry.widget is widget)

    def finish(self):
        for entry in self.pages:
            entry.widget.finish()


''')
insert(f,'SidebarPanelWidget.sidebar_visibility_changed','''    def finish(self) -> None:
        """Passive panels have no pending edit to submit."""
''')
patch(f,'ThreadSidebar.panel_entries','''        yield self.query_ancestor(ViewSettingsScope).configuration_panel''','''        yield from self.query_ancestor(ViewSettingsScope).configuration_panels''')
insert(f,'ThreadSidebar.__init__','''    def _compose_panels(self):
        yield PanelMenu(self.panel_entries(), self.navigation)

    def reveal_panel(self, widget):
        self.query_one(PanelMenu).activate(widget)
''')
f='src/toad/session_tracker.py'
patch(f,'SidebarState','''    panel_scroll_y: float = 0''','''    panel_scroll_y: float = 0
    panel_title: str = ""''')
f='src/toad/settings_scope.py'
patch(f,'ViewSettingsScope.configuration_panel','''    def configuration_panel(self): ...''','''    def configuration_panels(self): ...''')
f='src/toad/forms/form_view.py'
insert(f,'FieldView.of','''    @classmethod
    def from_field(cls, field: DeclaredField):
        """The field provider supplies the declaration used to select its presentation."""
        declaration = field.declaration
        parameter = ParameterInfo.create(
            name=declaration.name, param_type=field.annotation,
            current_value=field.value, default_value=declaration.default_value,
            description=declaration.description, is_required=declaration.is_required)
        return cls.showing(type(parameter).__mro__)(field)
''')
patch(f,'FieldView.of','''return [cls.showing(type(parameter).__mro__)(field)''','''return [cls.from_field(field)''')
f='src/toad/configured_view.py'
patch(f,'ObjectProperties','''class ObjectProperties(ObjectFormView, SidebarPanelWidget):
    """The sidebar edits the view's original state directly."""''','''class ObjectProperties(FillHeight, SidebarPanelWidget):
    """One declared settings entry; its form is built when that entry is opened."""

    def __init__(self, field):
        super().__init__()
        self.field = field

    def compose(self):
        self.form = ObjectFormView(self.field.state, [ObjectFieldView.from_field(self.field)])
        yield self.form

    def finish(self):
        self.form.finish()''')
patch(f,'ObjectConfigurationDialog','''    def __init__(self, state):
        super().__init__()
        self.form = ObjectFormView.whole(state)''','''    def __init__(self, panels):
        super().__init__()
        self.form = PanelMenu(panels, SidebarState())''')
patch(f,'ConfiguredView.configuration_panel','''    def configuration_panel(self):
        return SideBar.Panel("Properties", ObjectProperties.whole(self.configuration_state),
                             flex=True, collapsed=True)''','''    def configuration_panels(self):
        state = self.configuration_state
        for path in state.direct_parameter_paths():
            if state.shows(path.value):
                field = state.field(path.value)
                yield SideBar.Panel(field.label, ObjectProperties(field),
                                    id=f"settings-{path.value}", flex=True)''')
patch(f,'ConfiguredView.open_configuration','''ObjectConfigurationDialog(self.configuration_state)''','''ObjectConfigurationDialog(self.configuration_panels)''')
imp(f,'from toad.native_style import FillHeight')
imp(f,'from toad.forms.object_configuration import ObjectFieldView')
imp(f,'from toad.widgets.side_bar import PanelMenu')
f='src/toad/screens/comms.py'
s=Path(f).read_text(); start=s.index('    def make_thread_sidebar(self)'); end=s.index('    def compose(self)',start)
patch(f,'CommsScreen.make_thread_sidebar',s[start:end].rstrip(),'')
f='src/toad/widgets/session_thread_panels.py'
patch(f,'PlanSessionPanel.update','''                sidebar.query_one(f"#{self.declared_name}-panel", SideBarCollapsible).collapsed = False''','''                sidebar.reveal_panel(plan)''')
Path('.verification/view-sidebar-discovery/move.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'selected-object-panel-menu','operations':ops}]},indent=2))
