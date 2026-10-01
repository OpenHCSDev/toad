"""Compare one original certified snapshot; target never opens public storage."""
from pathlib import Path
from io import BytesIO
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import time

from agent_comms.field_codec import FieldCodec
from agent_comms.private_path import FileRevision
from agent_comms.wire_log import WireLog
from agent_comms.wire_record import WireScan
from agent_comms.bus_publication import decisions_wire

SOURCE = 'cac7bdf337d9e4dba888ce7c2093ddcc55802bc3'
TARGET = '4345bfc8aac0e4717450d4f79e6fe53e331f3ccf'
target = Path('/home/ts/wt/toad-s5-receiving-boundary-pair-20261001/.artifacts/runtime-s5-receiving61-20261001/bin/python')
assert json.loads(importlib.metadata.distribution('agent-comms').read_text('direct_url.json'))['vcs_info']['commit_id'] == SOURCE
started = time.monotonic()
wire = WireLog(Path('/var/tmp/agent-comms-live-20260927-wzjtqhza/bus.jsonl'))
with wire.certified_read(blocking=False) as source:
    source.stream.seek(0)
    payload = source.stream.read()
    marker = FieldCodec.encode(source.marker)
    revision = FileRevision.from_stat(wire.path.stat())
    source.require_current()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

def publication_proof(delivery):
    return {'wire_root_id':delivery.wire_root_id,
            'audience':FieldCodec.encode(delivery.audience),
            'decisions':decisions_wire(delivery.decisions),
            'decisions_digest':delivery.decisions_digest,
            'control':delivery.control,'resolver_version':delivery.resolver_version,
            'policy_version':delivery.policy_version,'manifest_codec':delivery.manifest_codec,
            'receipt':FieldCodec.encode(delivery.receipt)}

original_scan = WireScan(source.marker)
original_rows = []
for line in BytesIO(payload):
    if not line.strip():
        continue
    record = original_scan.read(line)
    original_rows.append({'type':type(record).__name__,
                          'public':record.message.to_wire(),
                          'publication_proofs':[publication_proof(d) for d in record.deliveries()],
                          'deliveries':len(record.deliveries())})

program = r'''
from io import BytesIO
import importlib.metadata,json,sys,hashlib
from agent_comms.field_codec import FieldCodec
from agent_comms.wire_record import WireScan
from agent_comms.wire_metadata import WireMetadata
from agent_comms.bus_publication import PRIVATE_WIRE_FIELD,decisions_wire
def publication_proof(delivery):
 return {'wire_root_id':delivery.wire_root_id,
         'audience':FieldCodec.encode(delivery.audience),
         'decisions':decisions_wire(delivery.decisions),
         'decisions_digest':delivery.decisions_digest,
         'control':delivery.control,'resolver_version':delivery.resolver_version,
         'policy_version':delivery.policy_version,'manifest_codec':delivery.manifest_codec,
         'receipt':FieldCodec.encode(delivery.receipt)}
v=json.load(sys.stdin)
pin=json.loads(importlib.metadata.distribution('agent-comms').read_text('direct_url.json'))['vcs_info']['commit_id']
assert pin==v['target']
scan=WireScan(FieldCodec.decode(WireMetadata,v['marker']))
actual=[];silent=0;defaulted=0;decision_fields=0
for line in BytesIO(bytes.fromhex(v['source'])):
 if not line.strip(): continue
 record=scan.read(line); messages=record.messages()
 if not messages:
  silent+=1
  assert record.to_wire()==json.loads(line)
  actual.append({'type':type(record).__name__,'observation':record.to_wire()})
  continue
 assert len(messages)==1
 message=messages[0];raw=json.loads(line)
 assert message.to_wire()=={k:x for k,x in raw.items() if k!=PRIVATE_WIRE_FIELD}
 assert not message.decision.retains_authored_choice
 assert message.decision.declared_name=='absent'
 assert 'decision' not in message.to_wire()
 defaulted+=1;decision_fields+=int('decision' in raw)
 actual.append({'type':type(record).__name__,'public':message.to_wire(),
                'publication_proofs':[publication_proof(d) for d in record.deliveries()],
                'deliveries':len(record.deliveries())})
assert actual==v['original'], 'Original typed public/private publication differs'
print(json.dumps({'rows':len(actual),'messages':defaulted,'silent_observations':silent,
 'attested_deliveries':sum(x.get('deliveries',0) for x in actual),
 'authored_choice_messages':0,'explicit_original_decision_fields':decision_fields,
 'final_sequence':scan.previous_sequence,
 'typed_public_private_equal':True,'original_public_envelope_equal':True,
 'ordinary_default_omitted':True,'target_pin':pin}))
'''
child=subprocess.run([str(target),'-c',program],input=json.dumps({
    'source':payload.hex(),'marker':marker,'original':original_rows,'target':TARGET}),
    text=True,capture_output=True,timeout=30)
if child.returncode:
    raise RuntimeError(child.stderr)
result=json.loads(child.stdout)
assert result['final_sequence']==original_scan.previous_sequence
result.update(state='PASS original certified typed public/private source equivalence',
              source_pin=SOURCE,source_interpreter=sys.executable,target_interpreter=str(target),
              source_bytes=len(payload),source_sha256=hashlib.sha256(payload).hexdigest(),
              original_typed_records_sha256=digest(original_rows),
              original_revision=FieldCodec.encode(revision),
              original_revision_unchanged_at_readback=revision==FileRevision.from_stat(wire.path.stat()),
              elapsed_seconds=time.monotonic()-started,
              public_writes=0,provider_calls=0,native_inputs=0,
              target_comms_initializations=0,old_journal_decodes=0,decision_to_task_carry=0,
              limitations=['Point-in-time snapshot; stopped-owner/source fences required at cutover',
                           'Zero silent observations is absence, not future observation compatibility proof',
                           'No journal/input/native/UNKNOWN mutation or replay; no public execution'])
output=Path(__file__).with_name('receipt.json')
output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
