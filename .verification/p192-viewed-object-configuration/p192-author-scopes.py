import ast,json,textwrap
from pathlib import Path
root=Path('/home/ts/wt/codex-live--P181--toad/src/toad')
ops=[]
def patch(file,target,old,new):
 ops.append({'operation':'patch_target','file_path':str(root/file),'target_qualname':target,'replacements':[{'old_source':old,'new_source':new}]})
def imp(file,text):ops.append({'operation':'ensure_import','file_path':str(root/file),'import_source':text})
scopes='''"""The configuration state owned by an application or one viewed object."""
from abc import abstractmethod
from objectstate import ObjectState
from textual.dom import DOMNode


class SettingsReader(DOMNode):
    @property
    def configuration_state(self) -> ObjectState:
        return self.query_ancestor(SettingsScope).configuration_state

    @property
    def settings(self):
        return self.configuration_state.to_resolved_object()


class SettingsScope(SettingsReader):
    @property
    @abstractmethod
    def configuration_state(self) -> ObjectState: ...

    def settings_widgets(self, widget_type):
        return self.walk_children(widget_type)


class ViewSettingsScope(SettingsScope):
    """A file, thread or channel owns its display overrides."""


class ConversationSettingsScope(ViewSettingsScope):
    """A thread or channel additionally owns conversation and composer settings."""
'''
ops.append({'operation':'create_file','file_path':str(root/'settings_scope.py'),'source':scopes})
patch('setting_declarations.py','SettingsDeclaration','    """An actual settings record, recognized by ObjectState\'s lazy configuration factory."""','''    """An actual settings record and the scopes its own field declarations admit."""

    configuration_scopes: ClassVar[tuple[type[SettingsScope], ...]] = ()

    def __init_subclass__(cls, *, scopes: tuple[type[SettingsScope], ...] = (), **kwargs):
        super().__init_subclass__(**kwargs)
        cls.configuration_scopes = scopes

    @classmethod
    def field_source(cls, name: str) -> type[SettingsDeclaration]:
        return next(owner for owner in cls.__mro__
                    if name in vars(owner).get("__annotations__", {}))

    @classmethod
    def admits_field(cls, name: str, scope: SettingsScope) -> bool:
        return any(isinstance(scope, admitted)
                   for admitted in cls.field_source(name).configuration_scopes)''')
imp('setting_declarations.py','from typing import ClassVar')
imp('setting_declarations.py','from toad.settings_scope import SettingsScope')
# Move each original field together with its help, keeping its source text intact.
p=root/'preferences.py';s=p.read_text();tree=ast.parse(s);ui=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='UiSettings')
groups=[('ViewUiSettings','SettingsDeclaration','ViewSettingsScope',{'column','column_width','column_alignment','scrollbar'}),('ConversationUiSettings','ViewUiSettings','ConversationSettingsScope',{'input','info_bar','status_line','agent_title','history_buffer_viewports','prune_low_mark','prune_excess','throbber'})]
lines=s.splitlines(keepends=True)
for name,base,scope,names in groups:
 chunks=[]
 for i,node in enumerate(ui.body):
  if not isinstance(node,ast.AnnAssign) or not isinstance(node.target,ast.Name) or node.target.id not in names:continue
  end=node.end_lineno
  if i+1<len(ui.body):
   following=ui.body[i+1]
   if isinstance(following,ast.Expr) and isinstance(following.value,ast.Constant) and isinstance(following.value.value,str):end=following.end_lineno
  chunk=''.join(lines[node.lineno-1:end]);chunks.append(chunk)
  patch('preferences.py','UiSettings',chunk.rstrip('\n'),'')
 source='@dataclass(frozen=True)\nclass '+name+'('+base+', scopes=('+scope+',)):\n'+''.join(chunks)
 ops.append({'operation':'insert_before_target','file_path':str(p),'target_qualname':'UiSettings','source':source})
patch('preferences.py','UiSettings','class UiSettings(SettingsDeclaration):','class UiSettings(ConversationUiSettings):')
for name in ('InputSettings','AgentSettings','ToolsSettings'):
 patch('preferences.py',name,f'class {name}(SettingsDeclaration):',f'class {name}(SettingsDeclaration, scopes=(ConversationSettingsScope,)):')
imp('preferences.py','from toad.settings_scope import ViewSettingsScope, ConversationSettingsScope')
# Scope readers compose with the existing DOM owners, not with a forwarding service.
patch('app_node.py','ToadNode','class ToadNode(DOMNode):','class ToadNode(SettingsReader):')
imp('app_node.py','from toad.settings_scope import SettingsReader')
Path('/home/ts/.cache/agent-scratch/codex-latency/p192-scopes.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'declared-field-scopes-and-shared-settings-readers','operations':ops}]},indent=2)+'\n')
