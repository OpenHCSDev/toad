import ast,json
from pathlib import Path
root=Path('/home/ts/wt/codex-live--P181--toad/src/toad');ops=[]
def create(file,source):ops.append(dict(operation='create_file',file_path=str(root/file),source=source))
def patch(file,target,old,new):ops.append(dict(operation='patch_target',file_path=str(root/file),target_qualname=target,replacements=[dict(old_source=old,new_source=new)]))
def imp(file,source):ops.append(dict(operation='ensure_import',file_path=str(root/file),import_source=source))
patch('object_configuration.py','ObjectSettingField','return get_base_type_for_lazy(super().owner_type)','return DeclaredField(self.state.defaults, self.path).owner_type')
patch('object_configuration.py','ObjectConfiguration','text = FieldCodec.dumps(ObjectSettingsDocument(self.identity, values))','text = json.dumps(FieldCodec.encode(ObjectSettingsDocument(self.identity, values)), indent=2, allow_nan=False)')
imp('object_configuration.py','import json')
patch('forms/form_view.py','FieldView','    @staticmethod\n    def of(state: ObjectState, parent: str = "") -> list[FieldView]:','''    field_type = DeclaredField

    @classmethod
    def admits(cls, field: DeclaredField) -> bool:
        return True

    @classmethod
    def of(cls, state: ObjectState, parent: str = "") -> list[FieldView]:''')
patch('forms/form_view.py','FieldView','''        return [FieldView.showing(type(parameter).__mro__)(DeclaredField(state, path))
                for path, parameter in ParameterFormService().parameters_for_state(state, parent)]''','''        return [cls.showing(type(parameter).__mro__)(field)
                for path, parameter in ParameterFormService().parameters_for_state(state, parent)
                if cls.admits(field := cls.field_type(state, path))]''')
patch('forms/form_view.py','GroupView','    def __init__(self, field: DeclaredField) -> None:','''    field_family = FieldView

    def __init__(self, field: DeclaredField) -> None:''')
patch('forms/form_view.py','GroupView','self.parts = FieldView.of(field.state, field.path.value)','self.parts = self.field_family.of(field.state, field.path.value)')
patch('forms/form_view.py','FormView','    DEFAULT_LAYOUT = StreamLayout','    field_family = FieldView\n    DEFAULT_LAYOUT = StreamLayout')
patch('forms/form_view.py','FormView.whole','FieldView.of(state)','cls.field_family.of(state)')
patch('forms/form_view.py','FormView.pages','FieldView.of(state)','cls.field_family.of(state)')
create('forms/object_configuration.py','''"""The same declared form in an object's sidebar and its context editor."""
from formbridge.forms.parameter_info_types import DirectDataclassInfo, ParameterInfo
from textual import events
from textual.widgets import Button, Static
from toad.forms.form_view import FieldView, ValueView, GroupView, FormView
from toad.object_configuration import ObjectSettingField
from toad.widgets.acting_button import ActingButton


class ObjectFieldView(FieldView):
    field_type = ObjectSettingField

    @classmethod
    def admits(cls, field):
        return field.state.shows(field.path.value)


class InheritSettingButton(ActingButton):
    def __init__(self, field):
        super().__init__("Use global default")
        self.field = field

    async def act(self):
        self.field.state.reset_parameter(self.field.path.value)


class ObjectValueView(ValueView, ObjectFieldView, shows=(ParameterInfo,)):
    def __init__(self, field):
        super().__init__(field)
        self.source = Static("", markup=False)
        self.inherit = InheritSettingButton(field)
        self.listen(events.Mount, lambda event: self.mark(False))

    def compose(self):
        yield from super().compose()
        yield self.source
        yield self.inherit

    def mark(self, changed):
        explicit = self.field.state.parameters[self.field.path.value] is not None
        super().mark(explicit)
        self.inherit.disabled = not explicit
        scope, owner = self.field.state.get_provenance(self.field.path.value)
        self.source.update("Override for this object" if explicit else
                           f"Inherited from global defaults · {owner.__name__}")


class ObjectGroupView(GroupView, ObjectFieldView, shows=(DirectDataclassInfo,)):
    field_family = ObjectFieldView


class ObjectFormView(FormView):
    field_family = ObjectFieldView
''')
create('configured_view.py','''"""A viewed object's state and its two presentations, inherited by files and conversations."""
from functools import cached_property
from textual import events, on
from textual.geometry import Region
from textual.widgets import Button
from toad.forms.object_configuration import ObjectFormView
from toad.object_configuration import ObjectConfiguration
from toad.screens.modal import DismissibleScreen, ModalPanel
from toad.forms.presentation import FormModal
from toad.settings_scope import ViewSettingsScope
from toad.sidebar_placement import ObjectSidebarPlacement
from toad.widgets.acting_button import DismissButton
from toad.widgets.comms_menu import ContextMenu
from toad.widgets.side_bar import SideBar, SidebarPanelWidget


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

    @cached_property
    def configuration_sidebar(self):
        return SideBar(SideBar.Panel("Properties", ObjectProperties.whole(self.configuration_state), flex=True),
                       placement_identity=ObjectSidebarPlacement, hide=True)

    def sidebars(self):
        return (*super().sidebars(), self.configuration_sidebar)

    @on(events.Unmount)
    def close_configuration(self):
        self.configuration_state.close()

    @on(events.MouseDown)
    def configuration_menu(self, event):
        if event.button != 3:
            return
        event.stop()
        event.prevent_default()
        # The properties form is shared; opening it never copies the state's values.
        ContextMenu.show(self.screen, Region.from_offset(event.screen_offset, (0, 0)),
                         self.display_name, [(self.open_configuration, "Properties…")],
                         callback=lambda chosen: chosen() if chosen is not None else None)

    def open_configuration(self):
        self.app.push_screen(ObjectConfigurationDialog(self.configuration_state))
''')
patch('widgets/history_anchor.py','HistoryWindow','class HistoryWindow(SettingsReader, ', 'class HistoryWindow(')
# Object placement inherits the existing viewed-object policy, retaining its own identity.
ops.append(dict(operation='insert_before_target',file_path=str(root/'sidebar_placement.py'),target_qualname='BandRoom',source='''class ObjectSidebarPlacement(ThreadSidebarPlacement):
    """Properties follow the viewed object, beside its other panels."""


'''))
imp('screens/session_view.py','from toad.configured_view import ConfiguredView')
imp('screens/session_view.py','from toad.settings_scope import ConversationSettingsScope')
patch('screens/session_view.py','SidebarSessionView','class SidebarSessionView[SidebarT: ThreadSidebar](WidgetView, NavigationOwner, SessionView):','class SidebarSessionView[SidebarT: ThreadSidebar](ConfiguredView, ConversationSettingsScope, WidgetView, NavigationOwner, SessionView):')
patch('screens/session_view.py','SidebarSessionView','return (self.thread_sidebar,)','return (self.thread_sidebar, self.configuration_sidebar)')
imp('screens/file_preview.py','from toad.configured_view import ConfiguredView')
imp('screens/file_preview.py','from toad.screens.session_view import SessionContents')
imp('screens/file_preview.py','from toad.column_layout import ColumnLayout')
patch('screens/file_preview.py','FilePreviewScreen','class FilePreviewScreen(SessionView,','class FilePreviewScreen(ConfiguredView, SessionView,')
patch('screens/file_preview.py','FilePreviewScreen','with Vertical():','with FileContents():')
ops.append(dict(operation='insert_before_target',file_path=str(root/'screens/file_preview.py'),target_qualname='FilePreviewScreen',source='''class FileContents(ColumnLayout, SessionContents):
    def apply_layout_preferences(self):
        super().apply_layout_preferences()
        self.apply_column_layout()


'''))
create('column_layout.py','''"""Column geometry shared by every viewed document."""
from textual.scrollable_container import ScrollableContainer
from toad.settings_scope import SettingsReader


class ColumnLayout(SettingsReader):
    def apply_column_layout(self):
        ui = self.settings.ui
        self.styles.max_width = max(10, ui.column_width) if ui.column else None
        for reader in self.walk_children(ScrollableContainer):
            reader.styles.scrollbar_size_vertical = ui.scrollbar.size
''')
# Conversation composes the same width/scrollbar procedure as a file.
s=(root/'widgets/conversation.py').read_text();t=ast.parse(s);c=next(n for n in t.body if isinstance(n,ast.ClassDef) and n.name=='Conversation')
patch('widgets/conversation.py','Conversation','class Conversation(','class Conversation(ColumnLayout, ')
patch('widgets/conversation.py','Conversation','''        ui = self.settings.ui
        self.styles.max_width = max(10, ui.column_width) if ui.column else None
        self.window.styles.scrollbar_size_vertical = ui.scrollbar.size''','''        self.apply_column_layout()''')
imp('widgets/conversation.py','from toad.column_layout import ColumnLayout')
# Remove the parallel file-menu identity/map: the actual action is the menu choice.
patch('project_link.py','ProjectFileLink','''        from toad.widgets.comms_menu import show_target_menu

        full_path = str(path)
        event.prevent_default()
        show_target_menu(widget.screen, Region.from_offset(event.screen_offset, (0, 0)), full_path,
                         [("copy_path", "Copy full path")],
                         {"copy_path": partial(widget.app.copy_to_clipboard, full_path)})''','''        from toad.widgets.comms_menu import ContextMenu

        full_path = str(path)
        event.prevent_default()
        copy_path = partial(widget.app.copy_to_clipboard, full_path)
        ContextMenu.show(widget.screen, Region.from_offset(event.screen_offset, (0, 0)), full_path,
                         [(copy_path, "Copy full path")],
                         callback=lambda chosen: chosen() if chosen is not None else None)''')
Path('/home/ts/.cache/agent-scratch/codex-latency/p192-ui.plan.json').write_text(json.dumps({'recipes':[dict(recipe_id='shared-object-properties-form-sidebar-and-context',operations=ops)]},indent=2)+'\n')
