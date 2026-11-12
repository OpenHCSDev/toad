import ast,json
from pathlib import Path
root=Path('/home/ts/wt/codex-live--P181--toad/src/toad');ops=[]
def create(file,source):ops.append(dict(operation='create_file',file_path=str(root/file),source=source))
def patch(file,target,old,new):ops.append(dict(operation='patch_target',file_path=str(root/file),target_qualname=target,replacements=[dict(old_source=old,new_source=new)]))
def imp(file,source):ops.append(dict(operation='ensure_import',file_path=str(root/file),import_source=source))
create('object_configuration.py','''"""A viewed object's overrides, with ObjectState owning inheritance and its source."""
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import cast

from agent_comms.nominal.field_codec import FieldCodec
from formbridge.forms.declared_fields import DeclaredField
from objectstate import ObjectState, ObjectStateRegistry, ScopeKey
from objectstate.lazy_factory import LazyDataclassFactory, get_base_type_for_lazy
from pydantic import JsonValue
from python_introspect import UnifiedParameterAnalyzer

from toad import atomic
from toad.setting_declarations import Effect, SettingsDeclaration
from toad.settings_scope import SettingsScope
from toad.tab_identity import TabIdentity


@dataclass(frozen=True)
class ObjectSettingsDocument:
    identity: TabIdentity
    values: dict[str, JsonValue]


class ObjectSettingField(DeclaredField):
    """The original concrete declaration, over a lazy field's actual state."""

    @property
    def declaration(self):
        return self.state.defaults.parameter_structure.declarations[self.path.value]

    @property
    def owner_type(self):
        return get_base_type_for_lazy(super().owner_type)


class ObjectConfiguration(ObjectState):
    """One view's explicit values; unassigned fields follow its live defaults."""

    def __init__(self, identity: TabIdentity, defaults: ObjectState,
                 directory: Path, owner: SettingsScope) -> None:
        self.identity, self.defaults, self.owner = identity, defaults, owner
        self.path = directory / "objects" / f"{identity.mode_name}.json"
        scope = str(ScopeKey.of("view", identity.mode_name))
        if ObjectStateRegistry.get_by_scope(scope) is not None:
            raise ValueError(f"Settings already open for {identity}")
        lazy_type = LazyDataclassFactory.make_lazy_simple(type(defaults.object_instance))
        super().__init__(lazy_type(), scope_id=scope, parent_state=defaults)
        if self.path.exists():
            document = FieldCodec.decode(ObjectSettingsDocument, FieldCodec.parse(self.path.read_text("utf-8")))
            if document.identity != identity:
                raise ValueError(f"Settings identity does not match {self.path}")
            for path, encoded in document.values.items():
                if path not in self.editable_paths:
                    raise ValueError(f"{path} cannot be overridden for {identity}")
                field = self.field(path)
                field.edit(FieldCodec.decode(field.annotation, encoded))
        self.mark_saved()
        ObjectStateRegistry.register(self)
        self.on_resolved_changed(self.apply_changes)
        self.on_state_changed(self.save_changes)

    def field(self, path: str) -> ObjectSettingField:
        return ObjectSettingField(self, self.parameter_structure.path(path))

    @cached_property
    def editable_paths(self) -> frozenset[str]:
        return frozenset(path.value for path in self.parameter_structure.leaf_paths()
                         if self.admits(path.value))

    def admits(self, path: str) -> bool:
        field = self.field(path)
        owner = field.owner_type
        return (issubclass(owner, SettingsDeclaration)
                and owner.admits_field(field.path.field_name, self.owner))

    def shows(self, path: str) -> bool:
        return any(name == path or name.startswith(path + ".") for name in self.editable_paths)

    def apply_changes(self, paths: set[str]) -> None:
        for path in paths & self.editable_paths:
            field = self.field(path)
            if (effect := field.metadata(Effect)) is not None:
                effect.apply(self.owner, field)

    def save_changes(self, paths: set[str]) -> None:
        if not paths:
            return
        values = {path: FieldCodec.encode(value, self.field(path).annotation)
                  for path, value in self.get_current_values().items()
                  if path in self.editable_paths and value is not None}
        text = FieldCodec.dumps(ObjectSettingsDocument(self.identity, values))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write(str(self.path), text)
        self.mark_saved()

    def close(self) -> None:
        self.off_resolved_changed(self.apply_changes)
        self.off_state_changed(self.save_changes)
        ObjectStateRegistry.unregister(self)
''')
# Scope reads follow the actual DOM owner; a detached widget starts from app defaults.
patch('settings_scope.py','SettingsReader','''    @property
    def configuration_state(self) -> ObjectState:
        return self.query_ancestor(SettingsScope).configuration_state''','''    @property
    def configuration_scope(self) -> SettingsScope:
        return next((node for node in self.walk_ancestors(with_self=True)
                     if isinstance(node, SettingsScope)), self.app)

    @property
    def configuration_state(self) -> ObjectState:
        return self.configuration_scope.configuration_state''')
# Compose the actual app default owner into the same settings scope lattice.
patch('textual_colours.py','ThemedApp','class ThemedApp(App[ReturnType], ResultShower, metaclass=_ThemedAppMeta):','class ThemedApp(SettingsScope, App[ReturnType], ResultShower, metaclass=_ThemedAppMeta):')
patch('textual_colours.py','ThemedApp','        self.saved_settings = self.open_settings()','''        self.saved_settings = self.open_settings()
        ObjectStateRegistry.register(self.saved_settings.state)''')
patch('textual_colours.py','ThemedApp','    def open_settings(self) -> SavedSettings:','''    @property
    def configuration_state(self) -> ObjectState:
        return self.saved_settings.state

    def open_settings(self) -> SavedSettings:''')
imp('textual_colours.py','from objectstate import ObjectState, ObjectStateRegistry')
imp('textual_colours.py','from toad.settings_scope import SettingsScope')
# Global traversal stays with the owner of retained views.
patch('setting_declarations.py','Effect','''        roots = (*app.workspace_sessions.views.values(), *app.screen_stack)
        return {widget for root in roots for widget in root.walk_children(widget_type)}''','''        return app.settings_widgets(widget_type)''')
patch('app.py','ToadApp','    def open_settings(self) -> SavedSettings:','''    def settings_widgets(self, widget_type):
        roots = (*self.workspace_sessions.views.values(), *self.screen_stack)
        return {widget for root in roots for widget in root.walk_children(widget_type)}

    def open_settings(self) -> SavedSettings:''')
# Effect readers use the target widget's own effective state.
patch('setting_effects.py','visibility','widget.display = field.value','widget.display = widget.configuration_state.get_resolved_value(field.path.value)')
old='''    for view in app.workspace_sessions.views.values():
        for window in view.query(HistoryWindow):
            window.presentation_budget = replace(window.presentation_budget, buffer_viewports=field.value)
            window.request_preparation()'''
new='''    for window in Effect.open_widgets(app, HistoryWindow):
        value = window.configuration_state.get_resolved_value(field.path.value)
        window.presentation_budget = replace(window.presentation_budget, buffer_viewports=value)
        window.request_preparation()'''
patch('setting_effects.py','history_buffer_viewports',old,new)
patch('setting_widget.py','SettingVisibility','class SettingVisibility:','class SettingVisibility(SettingsReader):')
patch('setting_widget.py','SettingVisibility','self.app.saved_settings.state.get_resolved_value','self.configuration_state.get_resolved_value')
imp('setting_widget.py','from toad.settings_scope import SettingsReader')
# Reuse the inherited reader for widgets that consume local settings.
for file,names in [('widgets/prompt.py',('PromptLabel','PromptContainer')),('widgets/history_anchor.py',('HistoryWindow',)),('screens/main.py',('MainScreen',))]:
 s=(root/file).read_text();tree=ast.parse(s)
 for name in names:
  node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==name)
  # Existing ToadNode-bearing owners already acquire SettingsReader through that parent.
  if name=='MainScreen':continue
  header=s.splitlines()[node.lineno-1]
  patch(file,name,'class '+name+'(','class '+name+'(SettingsReader, ')
 imp(file,'from toad.settings_scope import SettingsReader')
# Replace reads only for the admitted setting families, preserving app-owned global settings.
for file in ('widgets/prompt.py','widgets/conversation.py','widgets/history_anchor.py','widgets/tool_call.py','screens/main.py','screens/session_view.py'):
 s=(root/file).read_text();tree=ast.parse(s)
 for cls in (n for n in tree.body if isinstance(n,ast.ClassDef)):
  chunk=ast.get_source_segment(s,cls)
  new=chunk
  for prefix in ('ui.input','ui.prune_','ui.history_buffer_viewports','ui.column','ui.scrollbar','ui.throbber','tools.'):
   new=new.replace('self.app.settings.'+prefix,'self.settings.'+prefix)
  # Two methods read the complete ui record and then local fields.
  if file=='widgets/conversation.py':new=new.replace('ui = self.app.settings.ui','ui = self.settings.ui')
  if file=='widgets/prompt.py':new=new.replace('ui = self.app.settings.ui','ui = self.settings.ui')
  if new!=chunk:patch(file,cls.name,chunk,new)
Path('/home/ts/.cache/agent-scratch/codex-latency/p192-state.plan.json').write_text(json.dumps({'recipes':[dict(recipe_id='one-lazy-object-state-and-scoped-consumers',operations=ops)]},indent=2)+'\n')
