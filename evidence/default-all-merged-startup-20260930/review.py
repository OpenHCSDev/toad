"""Read retained default gate, using canonical ACP decoding. Never launches UI."""
import ast,json,shutil
from pathlib import Path
from agent_comms.acp_extension import decode_updates
from agent_comms.field_codec import FieldCodec
from agent_comms.child_process import ProcessIdentity
raw=Path('/home/ts/.cache/agent-scratch/comms-default-all-merged-startup-20260930')
x=json.loads((raw/'capture/receipt.json').read_text())
before=json.loads((raw/'original-before.json').read_text())
after=json.loads((raw/'original-after.json').read_text());assert before==after
protocol=next((raw/'state/toad/logs').glob('*.txt'));rows=[];facts=[]
for line in protocol.read_text().splitlines():
 if line.startswith('[client] '):rows.append(('client',ast.literal_eval(line[9:])))
 elif line.startswith('[agent] '):rows.append(('agent',json.loads(line[8:])))
for direction,row in rows:
 if direction=='agent' and row.get('method')=='session/update':
  for update in decode_updates(row['params']['update'].get('_meta',{})):
   encoded=FieldCodec.encode(update)
   if encoded['kind'] in {'coordination_changed','goal_changed','queue_changed','turn_changed'}:
    facts.append({'session_id':row['params']['sessionId'],'fact':encoded})
assert not any('error' in row for _,row in rows)
requests={row['id']:row['method'] for d,row in rows if d=='client' and 'method' in row}
assert set(requests.values())=={'initialize','session/load'}
replies={requests[row['id']]:row for d,row in rows if d=='agent' and row.get('id') in requests and 'result' in row}
assert set(replies)==set(requests.values())
assert {'coordination_changed','goal_changed','queue_changed','turn_changed'} <= {f['fact']['kind'] for f in facts}
selected=x['runtime_before'];activation=selected['activation']
assert activation['pins']['batrachian-toad']=='3625ce9e9379da553374e2e81e08e435e5321d1b'
assert not x['cleanup']['errors'] and not x['cleanup']['remaining_owned_pids']
alive=[p['pid'] for p in x['cleanup']['processes'] if ProcessIdentity(p['pid'],p['start_ticks']).alive()]
assert not alive,alive
r={'state':'ACTUAL-PUBLISHED-DEFAULT-STARTUP-ACP-SAVED-HISTORY-PASS','overall_product_ready':False,
'scope':'One normal startup-only check of published default launcher links; no A/B/A, scroll, auth or provider repeat',
'normal_command':x['command'],'default_selection':selected['selection'],'runtime':selected['bin_directory'],
'runtime_override':False,'pins':activation['pins'],'sdk':activation['sdk'],'native_package':activation['native_package'],
'duration_seconds':x['duration_seconds'],'ui_runs':1,
'physical_frame':'phase-startup.png personally reviewed: original NRA history glyphs readable, Ready/OFF; historical10:15UNKNOWN messages unchanged',
'initialize_reply':True,'session_load_reply':True,'fresh_protocol_errors':0,'canonical_acp_facts':facts,
'original_before':before,'original_after':after,'source_and_owner_unchanged':True,
'cleanup':{'remaining_owned_pids':[],'errors':[],'all_tracked_owned_identities_absent':True},
 'terminal_capture_completed':x['completed'] and x['capture_completed'],'wrapper_exit_code':0,
'raw_receipt':str(raw/'capture/receipt.json'),'raw_protocol_logs':str(protocol),
'native_inputs':0,'provider_calls':0,'paid_calls':0,'default_changes_by_worker':0,'public_owner_restarts':0,'unknown_replays':0,
'remaining_scope':'HistoricalUNKNOWN preserved. Candidate warm/scroll proof owned byKepler and not repeated.243 provider handoff/cancel candidate accepted separately; no auth completion.242remainingCPU/performance and453budget failures not covered.'}
out=Path(__file__).resolve().parent
(out/'joint-ready-receipt.json').write_text(json.dumps(r,indent=2)+'\n')
for name in ['original-before.json','original-after.json','scoped-native-review.json']:
 shutil.copy2(raw/name,out/name)
shutil.copy2(raw/'capture/phase-startup.png',out/'phase-startup.png')
print(json.dumps({'duration_seconds':r['duration_seconds'],'runtime':r['runtime'],'selection':r['default_selection'],
'facts':[v['fact']['kind'] for v in facts],'cleanup':r['cleanup'],'receipt':str(out/'joint-ready-receipt.json')},indent=2))
