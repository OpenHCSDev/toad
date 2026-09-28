"""One-time current caller import migration; not a runtime symbol registry."""
import ast
import json
from collections import defaultdict
from pathlib import Path

root = Path(__file__).resolve().parents[2]
declarations = json.loads(Path('/home/ts/wt/comms-c0-declarations-20260928/evidence/c0-declarations/symbol-owners.json').read_text())
operations = json.loads(Path('/home/ts/wt/comms-refactor-c0-operations-20260928/evidence/c0-operations/caller-map.json').read_text())
owners = {**declarations, **operations['symbols']}
changed=[]
for folder in ('src', 'tests', 'benchmarks'):
 for path in (root/folder).rglob('*.py'):
  source=path.read_text();tree=ast.parse(source);lines=source.splitlines(keepends=True)
  starts=[0]
  for line in lines:starts.append(starts[-1]+len(line))
  edits=[]
  for node in ast.walk(tree):
   if not isinstance(node,ast.ImportFrom) or node.module not in ('agent_comms','agent_comms.declarations','agent_comms.operations'):continue
   groups=defaultdict(list)
   for item in node.names:
    module='agent_comms.'+owners[item.name] if item.name in owners else node.module
    groups[module].append(item.name+(' as '+item.asname if item.asname else ''))
   replacement=('\n'+' '*node.col_offset).join('from '+module+' import '+', '.join(names) for module,names in groups.items())
   begin=starts[node.lineno-1]+node.col_offset;end=starts[node.end_lineno-1]+node.end_col_offset
   edits.append((begin,end,replacement))
  for begin,end,replacement in sorted(edits,reverse=True):source=source[:begin]+replacement+source[end:]
  if source!=path.read_text():path.write_text(source);changed.append(str(path.relative_to(root)))
print(json.dumps(changed,indent=2))
