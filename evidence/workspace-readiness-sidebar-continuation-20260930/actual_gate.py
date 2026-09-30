"""One approved installed249 current-route recording, never a provider input."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

from agent_comms.active_route import read_active_route
from agent_comms.field_codec import FieldCodec
from agent_comms.registration import Registration

BASE = Path('/home/ts/wt/toad-workspace-readiness-sidebar-continuation-20260930')
RUNTIME = BASE / '.artifacts/installed-sidebar-custody-249/bin'
OUTPUT = Path('/home/ts/.cache/agent-scratch/toad-sidebar-custody-249-20260930-attempt01')
TOOLS = BASE / 'tests/tools'
sys.path.insert(0, str(TOOLS))
from record_installed_tui import ProcessOwner


def sources(route):
    rows = []
    registration = Registration(route.root / 'registry.json')
    for name in ('nra-architecture', 'nra-domain-mapping'):
        thread = registration.require(name)
        identity = thread.process_identity
        assert identity is not None and identity.alive()
        assert thread.active_turn is None, name
        journal = Path(thread.session_file)
        with journal.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        rows.append(dict(thread=name, owner=FieldCodec.encode(identity),
                         journal=str(journal), bytes=journal.stat().st_size, sha256=digest))
    assert rows[0]['bytes'] >= 40_000_000
    return rows


def main():
    OUTPUT.mkdir(exist_ok=False)
    route = read_active_route()
    assert route is not None
    route.observe_root()
    assert route.native_package == Path('/home/ts/.local/share/agent-comms/native-current-593b978a717ae8f6/node_modules/@earendil-works/pi-coding-agent')
    before = sources(route)
    env = dict(os.environ)
    for key in ('PYTHONPATH', 'NO_COLOR'):
        env.pop(key, None)
    env.update(AGENT_COMMS_RUNTIME_ROOT=str(RUNTIME), XDG_STATE_HOME=str(OUTPUT / 'state'))
    state = Path.home() / '.local/state/toad/toad.db'
    copy = OUTPUT / 'state/toad/toad.db'
    copy.parent.mkdir(parents=True)
    with sqlite3.connect(state.as_uri() + '?mode=ro', uri=True) as original:
        with sqlite3.connect(copy) as target:
            original.backup(target)
    script = OUTPUT / 'actions.xdo'
    common = [str(RUNTIME / 'python'), str(TOOLS / 'record_installed_tui.py'),
              '--capture-target', 'existing_thread', '--journey', 'warm_scroll',
              '--peer-thread', 'nra-domain-mapping', '--capture-state',
              '--scroll-hold-seconds', '4', '--scroll-idle-seconds', '15',
              '--max-duration', '100']
    command = [*common, '--actions', str(script), '--output', str(OUTPUT / 'capture'),
               '--owner', 'Heisenberg249-current-route', '--fit-window',
               '--width', '1280', '--height', '900', '--startup-wait', '12', '--tail-seconds', '2',
               '--profile', '--profile-threads', 'gil', '--profile-rate', '25',
               '--review-timing', 'deferred', '--review-phase', 'down',
               '--review-phase', 'return-a', '--review-phase', 'switch-b',
               '--', '/home/ts/bin/toad-comms', 'nra-architecture']
    receipt = dict(owner='Heisenberg249', purpose='one approved meaningful candidate workflow',
                   stage=str(RUNTIME), sources_before=before, canonical_root=str(route.root), active_route=FieldCodec.encode(route),
                   argv=command, source='c191f29a45f1c7374dc44e88024dc71fc232f729',
                   scope='read-only native source; local draft/Undo only; no provider or public lifecycle')
    (OUTPUT / 'admission.json').write_text(json.dumps(receipt, indent=2) + '\n')
    processes = ProcessOwner()
    try:
        processes.run([*common, '--write-journey-script', str(script)], env, timeout=15)
        with (OUTPUT / 'gate.log').open('w') as log:
            processes.run(command, env, stdout=log, stderr=log, timeout=130)
        receipt['driver_exit_code'] = 0
    finally:
        receipt['cleanup'] = processes.cleanup()
        receipt['sources_after'] = sources(route)
        assert read_active_route() == route
        receipt['originals_unchanged'] = receipt['sources_after'] == before
        (OUTPUT / 'custody.json').write_text(json.dumps(receipt, indent=2) + '\n')
        assert receipt['originals_unchanged']
    print(OUTPUT)


if __name__ == '__main__':
    main()
