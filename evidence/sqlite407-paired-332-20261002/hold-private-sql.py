"""Bound one actual private SQL resource for the existing physical UI driver."""
from pathlib import Path
import json, select, sys, time
from agent_comms.coordinator import Coordination

root = Path(sys.argv[1]).resolve(strict=True)
# A capture's owned HOME fixture is disjoint from the actual public /var/tmp root.
root.relative_to(Path('/home/ts'))
database = root / 'coordination.sqlite3'
if not database.is_file():
    raise SystemExit('The original private coordinator must already exist')
with Coordination(str(database), lock_timeout=0.05) as coordination:
    with coordination.session.irreversible_admission():
        print(json.dumps({'phase':'exclusive-acquired','root':str(root),
                          'monotonic_ns':time.monotonic_ns()}),flush=True)
        # Owned process stdin is the release resource. A failed driver cannot
        # leave a permanent exclusion; this test operation is bounded to20s.
        if not select.select([sys.stdin],[],[],20)[0]:
            raise TimeoutError('Physical driver did not release its owned SQL resource')
        sys.stdin.buffer.read(1)
print(json.dumps({'phase':'exclusive-released','monotonic_ns':time.monotonic_ns()}),flush=True)
