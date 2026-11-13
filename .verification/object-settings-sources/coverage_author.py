import json
from pathlib import Path
r=Path.cwd();ops=[]
def patch(f,t,o,n):ops.append(dict(operation='patch_target',file_path=str(r/f),target_qualname=t,replacements=[dict(old_source=o,new_source=n)]))
def insert(f,t,s):ops.append(dict(operation='insert_before_target',file_path=str(r/f),target_qualname=t,source=s))
insert('src/toad/history_coverage.py','HistoryCoverage.outgoing','''    def is_available(self) -> bool:
        """Whether this source has published saved history, without reading its cursor."""
        return False

''')
insert('src/toad/history_coverage.py','PageCoverage.outgoing','''    def is_available(self) -> bool:
        return True

''')
patch('tools/physical_ui_remote.py','ObserveOperation.execute','history.state.coverage.retained_through(history) for history in histories','history.state.coverage.is_available() for history in histories')
Path('.verification/object-settings-sources/coverage.plan.json').write_text(json.dumps({'recipes':[{'recipe_id':'ask-the-coverage-owner-about-publication','operations':ops}]},indent=2))
