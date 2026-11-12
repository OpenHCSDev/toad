import ast,json
from pathlib import Path
r=Path('/home/ts/wt/codex-live--P181--toad/src/toad');ops=[]
def patch(f,t,o,n):ops.append(dict(operation='patch_target',file_path=str(r/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def imp(f,s):ops.append(dict(operation='ensure_import',file_path=str(r/f),import_source=s))
ops.append(dict(operation='insert_after_target',file_path=str(r/'widgets/side_bar.py'),target_qualname='ThreadSidebar',source='''class LazyThreadSidebar(ThreadSidebar):
    """Create panel widgets only when this view's sidebar opens."""

    def __init__(self, *panels, **kwargs):
        super().__init__(*panels, defer_mount=True, **kwargs)

    @property
    def wants_panels(self) -> bool:
        return super().wants_panels and not self.collapsed

    @abstractmethod
    def make_panels(self): ...

    def _compose_panels(self):
        if not self.panels:
            self.panels.extend(self.make_panels())
        yield from super()._compose_panels()
'''))
imp('widgets/side_bar.py','from abc import abstractmethod')
patch('widgets/session_thread_sidebar.py','SessionThreadSidebar','class SessionThreadSidebar(ThreadSidebar, NativePresentation):','class SessionThreadSidebar(LazyThreadSidebar, NativePresentation):')
patch('widgets/session_thread_sidebar.py','SessionThreadSidebar','super().__init__(state=screen._thread_sidebar_state, defer_mount=True)','super().__init__(state=screen._thread_sidebar_state)')
s=(r/'widgets/session_thread_sidebar.py').read_text();cls=next(n for n in ast.parse(s).body if isinstance(n,ast.ClassDef) and n.name=='SessionThreadSidebar');node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='wants_panels');start=node.decorator_list[0].lineno;old='\n'.join(s.splitlines()[start-1:node.end_lineno]);patch('widgets/session_thread_sidebar.py','SessionThreadSidebar',old,'')
old='''    def _compose_panels(self) -> ComposeResult:
        if not self.panels:
            screen = self._owner()
            if screen is None:
                raise ReferenceError("The session sidebar owner has retired")
            self.panels.extend(owner.compose_panel(screen) for owner in self._panel_owners)
        yield from super()._compose_panels()'''
new='''    def make_panels(self):
        screen = self._owner()
        if screen is None:
            raise ReferenceError("The session sidebar owner has retired")
        return (owner.compose_panel(screen) for owner in self._panel_owners)'''
patch('widgets/session_thread_sidebar.py','SessionThreadSidebar',old,new)
imp('widgets/session_thread_sidebar.py','from toad.widgets.side_bar import LazyThreadSidebar')
patch('configured_view.py','ObjectSidebar','class ObjectSidebar(ThreadSidebar):\n    placement_type = ObjectSidebarPlacement','''class ObjectSidebar(LazyThreadSidebar):
    placement_type = ObjectSidebarPlacement

    def __init__(self, configuration):
        self.configuration = configuration
        super().__init__(state=SidebarState())

    def make_panels(self):
        return (SideBar.Panel("Properties", ObjectProperties.whole(self.configuration), flex=True),)''')
imp('configured_view.py','from toad.widgets.side_bar import LazyThreadSidebar')
patch('configured_view.py','ConfiguredView','''        return ObjectSidebar(SideBar.Panel("Properties", ObjectProperties.whole(self.configuration_state), flex=True),
                             state=SidebarState())''','''        return ObjectSidebar(self.configuration_state)''')
patch('forms/form_view.py','FormView.follow_state','''        self.state.on_state_changed(self.marks_changed)
        self.marks_changed(self.state.dirty_fields)''','''        self.state.on_state_changed(self.marks_changed)
        self.values_changed(set(self.values))
        self.marks_changed(self.state.dirty_fields)''')
# Avoid keeping the inherited parent name as a second unused import.
for file,names in [('configured_view.py',['ThreadSidebar']),('widgets/session_thread_sidebar.py',['ThreadSidebar','ComposeResult'])]:
 ops.append(dict(operation='remove_import_bindings',file_path=str(r/file),bound_names=names))
Path('/home/ts/.cache/agent-scratch/codex-latency/p192-lazy-panels.plan.json').write_text(json.dumps({'stages':[{'recipes':[dict(recipe_id='inherit-one-lazy-view-sidebar-lifecycle',operations=[op for op in ops if op['operation']!='remove_import_bindings'])]},{'recipes':[dict(recipe_id='remove-replaced-parent-imports',operations=[op for op in ops if op['operation']=='remove_import_bindings'])]}]},indent=2))
