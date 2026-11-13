import json
from pathlib import Path
root=Path.cwd(); ops=[]
def p(f,t,o,n): ops.append(dict(operation='patch_target',file_path=str(root/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def insert(f,t,s): ops.append(dict(operation='insert_before_target',file_path=str(root/f),target_qualname=t,source=s))
f='src/toad/screens/session_view.py'
p(f,'SidebarSessionView', '''    @cached_property
    def _thread_sidebar_state(self) -> SidebarState:
        return SidebarState()

    @abstractmethod
    def make_thread_sidebar(self) -> SidebarT: ...''','')
f='src/toad/configured_view.py'
insert(f,'ConfiguredView.make_thread_sidebar','''    @cached_property
    def _thread_sidebar_state(self):
        return SidebarState()
''')
p(f,'ConfiguredView.make_thread_sidebar','return ThreadSidebar(state=SidebarState())','return ThreadSidebar(state=self._thread_sidebar_state)')
insert(f,'ObjectProperties.compose','''    @property
    def panel_identity(self):
        return self.field.path
''')
f='src/toad/widgets/side_bar.py'
insert(f,'SidebarPanelWidget.finish','''    @property
    def panel_identity(self):
        """The nominal widget role identifies a panel across its lazy realizations."""
        return type(self)
''')
p(f,'PanelMenu.__init__','if entry.title == navigation.panel_title','if entry.widget.panel_identity == navigation.panel_identity')
p(f,'PanelMenu.show_panel','self.navigation.panel_title = entry.title','self.navigation.panel_identity = entry.widget.panel_identity')
f='src/toad/session_tracker.py'
p(f,'SidebarState','panel_title: str = ""','panel_identity: object = None')
f='tests/textual/test_sidebar_projection.py'
p(f,'test_view_menu_discovers_settings_and_keeps_each_objects_state','menu.navigation.panel_title == other.title','menu.navigation.panel_identity == other.widget.panel_identity')
p(f,'test_view_menu_discovers_settings_and_keeps_each_objects_state','menu.navigation.panel_title == ui_entry.title','menu.navigation.panel_identity == ui_entry.widget.panel_identity')
Path('.verification/view-sidebar-discovery/lifecycle.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'inherit-original-sidebar-lifecycle','operations':ops}]},indent=2))
