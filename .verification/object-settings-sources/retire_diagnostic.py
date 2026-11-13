import json
from pathlib import Path
r=Path.cwd();p=json.loads(Path('.verification/object-settings-sources/select-observation.plan.json').read_text())
p['recipes'][0]['recipe_id']='retire-temporary-select-geometry-observation'
for op in p['recipes'][0]['operations']:
    for pair in op['replacements']:
        pair['old_source'],pair['new_source']=pair['new_source'],pair['old_source']
Path('.verification/object-settings-sources/retire-diagnostic.plan.json').write_text(json.dumps(p,indent=2))
