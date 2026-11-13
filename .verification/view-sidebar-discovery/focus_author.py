import json
from pathlib import Path
root=Path.cwd(); ops=[]
def p(f,t,o,n): ops.append(dict(operation='patch_target',file_path=str(root/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def ins(f,t,s): ops.append(dict(operation='insert_before_target',file_path=str(root/f),target_qualname=t,source=s))
f='src/toad/widgets/side_bar.py'
ins(f,'SideBar.toggle','''    def focus_contents(self):
        self.panels_viewport.focus()
''')
p(f,'SideBar.toggle','''            if title := self.query_one_optional("SideBarCollapsible CollapsibleTitle"):
                title.focus()''','''            if self.panels_loaded:
                self.focus_contents()''')
ins(f,'ThreadSidebar.reveal_panel','''    def focus_contents(self):
        self.query_one(PanelPicker).focus()
''')
f='src/toad/widgets/session_thread_panels.py'
p(f,'PlanSessionPanel.update','''        title = self.declared_name.title()
        if entries:
            sidebar.navigation.panels_collapsed[title] = False
''','')
Path('.verification/view-sidebar-discovery/focus.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'inherit-panel-focus-and-delete-old-intent-write','operations':ops}]},indent=2))
