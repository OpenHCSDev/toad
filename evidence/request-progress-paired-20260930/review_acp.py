"""Decode the completed journey's actual retained ACP logs; never launches it."""
import argparse
import ast
import json
from pathlib import Path
from agent_comms.acp_extension import decode_updates, TurnChangedUpdate
from agent_comms.field_codec import FieldCodec
from agent_comms.turn_phase import ModelWaitPhase

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
base = args.output.resolve()
proof = base / 'proof'
logs = sorted((base / 'fixture/application/state/toad/logs').glob('*.txt'))
assert logs, 'No actual installed ACP session logs retained'
turns, measured, errors, protocols = [], [], [], []
for path in logs:
    rows = []
    for line in path.read_text().splitlines():
        if line.startswith('[client] '):
            rows.append(('client', ast.literal_eval(line[9:])))
        elif line.startswith('[agent] '):
            rows.append(('agent', json.loads(line[8:])))
    requests = {row['id']: row['method'] for direction, row in rows
                if direction == 'client' and 'method' in row and 'id' in row}
    replies = []
    for direction, row in rows:
        if direction != 'agent':
            continue
        if 'error' in row:
            errors.append({'path': str(path), 'row': row})
        if row.get('id') in requests and 'result' in row:
            replies.append(requests[row['id']])
        if row.get('method') != 'session/update':
            continue
        params = row['params']
        for fact in decode_updates(params['update'].get('_meta', {})):
            if not isinstance(fact, TurnChangedUpdate):
                continue
            record = {'path': str(path), 'session_id': params['sessionId'],
                      'fact': FieldCodec.encode(fact)}
            turns.append(record)
            phase = fact.state.phase
            if isinstance(phase, ModelWaitPhase) and phase.source is not None:
                measured.append({**record, 'native_progress': FieldCodec.encode(phase.source)})
    protocols.append({'path': str(path), 'request_methods': list(requests.values()),
                      'replied_methods': replies})
assert not errors, errors
assert measured, 'New native ModelWait.source not observed through actual installed ACP'
assert any(record['fact']['state']['active'] is None for record in turns)
for protocol in protocols:
    assert {'initialize', 'session/load'} <= set(protocol['replied_methods']), protocol
receipt = {'typed_turn_callbacks': len(turns), 'measured_model_wait_callbacks': len(measured),
           'native_stages': sorted({record['native_progress']['stage'] for record in measured}),
           'fresh_protocol_errors': errors, 'protocols': protocols,
           'actual_typed_native_progress': measured,
           'idle_observed': True,
           'clock_semantics': 'Native elapsed/source values only; no subtraction between process clocks',
           'scope': 'Existing native first-fork UI journey; no real-provider dwell or queue timing claim'}
(proof / 'canonical-acp-progress.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({key: receipt[key] for key in (
    'typed_turn_callbacks', 'measured_model_wait_callbacks', 'native_stages',
    'fresh_protocol_errors', 'idle_observed')}))
