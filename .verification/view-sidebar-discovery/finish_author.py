import json
from pathlib import Path
root=Path.cwd(); ops=[]
def p(f,t,o,n): ops.append(dict(operation='patch_target',file_path=str(root/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
p('src/toad/forms/form_view.py','FieldView.of','return [cls.from_field(field)','return [cls.showing(type(parameter).__mro__)(field)')
p('src/toad/forms/form_view.py','FieldView.from_field','current_value=field.value, default_value=declaration.default_value,','current_value=None, default_value=declaration.default_value,')
p('src/toad/widgets/session_thread_panels.py','PlanSessionPanel.update', '''        if plan := sidebar.query_one_optional(Plan):
            plan.entries = entries
            if entries:
                sidebar.reveal_panel(plan)''','''        if sidebar.panels_loaded:
            plan = next(panel.widget for owner, panel in zip(sidebar._panel_owners, sidebar.panels)
                        if owner is self)
            plan.entries = entries
            if entries:
                sidebar.reveal_panel(plan)''')
for f,names in [('src/toad/screens/comms.py',['CoordinationStatus','RelationshipSort','ThreadCommsSidebar']),('src/toad/widgets/session_thread_panels.py',['SideBarCollapsible'])]:
    ops.append(dict(operation='remove_import_bindings',file_path=str(root/f),bound_names=names))
Path('.verification/view-sidebar-discovery/finish.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'migrate-panel-consumers','operations':ops}]},indent=2))
