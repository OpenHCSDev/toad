import json
from pathlib import Path
r=Path.cwd();ops=[]
def patch(f,t,o,n):ops.append(dict(operation='patch_target',file_path=str(r/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def insert(f,t,s):ops.append(dict(operation='insert_before_target',file_path=str(r/f),target_qualname=t,source=s))
patch('tools/physical_ui_remote.py','ObserveOperation.execute','history.state.reports_coverage for history in histories','history.state.coverage.retained_through(history) for history in histories')
patch('src/toad/widgets/model_switcher.py','SessionModelEditor.opened','self.focus_content(False)','self.query_ancestor(SessionForm).open_model(self)')
insert('src/toad/widgets/model_switcher.py','SessionForm.dismiss_control','''    def open_model(self, editor):
        """An inline form paints its model choices without taking keyboard focus."""
        editor.configuration_changed()

''')
insert('src/toad/widgets/model_switcher.py','PopupSessionForm.dismiss_control','''    def open_model(self, editor):
        if self.query_ancestor(ModelSwitcher).is_open:
            editor.focus_content(False)

''')
Path('.verification/object-settings-sources/inspection.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'read-the-held-coverage-and-retain-form-focus','operations':ops}]},indent=2))
