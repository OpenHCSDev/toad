"""One-time migration of fixture Comms receivers and their patch targets."""
import ast,json
from pathlib import Path
m=json.loads(Path('/home/ts/wt/comms-refactor-c0-operations-20260928/evidence/c0-operations/caller-map.json').read_text())
mapping={**m['methods'],**m['fields']}
def factory(n):
 return isinstance(n,ast.Call) and ast.unparse(n.func) in ('Comms','wire')
for path in Path('tests').rglob('*.py'):
 source=path.read_text();tree=ast.parse(source);names={'comms'}
 for n in ast.walk(tree):
  if isinstance(n,ast.Assign) and factory(n.value):
   names.update(ast.unparse(t) for t in n.targets if isinstance(t,(ast.Name,ast.Attribute)))
 def known(n):
  r=ast.unparse(n)
  return r in names or r in ('self.comms','view._wire','new_view._wire','chat._wire','channel._wire') or factory(n)
 lines=source.splitlines(keepends=True);starts=[0]
 for line in lines:starts.append(starts[-1]+len(line))
 def span(n):return starts[n.lineno-1]+n.col_offset,starts[n.end_lineno-1]+n.end_col_offset
 edits=[]
 for n in ast.walk(tree):
  if isinstance(n,ast.Attribute) and n.attr in mapping and known(n.value):
   end=span(n)[1];edits.append((end-len(n.attr),end,mapping[n.attr]))
  if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='object' and len(n.args)>=2:
   obj,key=n.args[:2]
   if not isinstance(key,ast.Constant) or not isinstance(key.value,str) or key.value not in mapping:continue
   typed=isinstance(obj,ast.Call) and ast.unparse(obj.func)=='type' and len(obj.args)==1 and known(obj.args[0])
   if not known(obj) and not typed:continue
   parts=mapping[key.value].split('.')
   if len(parts)<2:continue
   inner=obj.args[0] if typed else obj
   replacement=ast.unparse(inner)+'.'+'.'.join(parts[:-1])
   edits.append((*span(obj),'type('+replacement+')' if typed else replacement))
   edits.append((*span(key),repr(parts[-1])))
 for a,b,v in sorted(set(edits),reverse=True):source=source[:a]+v+source[b:]
 source=source.replace('from agent_comms.operations import wire','from agent_comms.comms import wire').replace('from agent_comms import wire','from agent_comms.comms import wire')
 source=source.replace('agent_comms.operations.schedule_private_candidate_after_commit','agent_comms.messaging.schedule_private_candidate_after_commit')
 source=source.replace('patch("agent_comms.wire", construct), patch("agent_comms.operations.wire", construct),','patch("agent_comms.comms.wire", construct),')
 source=source.replace('agent_comms.operations.wire','agent_comms.comms.wire')
 if source!=path.read_text():path.write_text(source)
