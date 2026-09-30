"""Adopt the certified unused private sources; one current-format ENV capture."""
import asyncio
import json
import os
from pathlib import Path
import shlex
import sys

from agent_comms.active_route import read_active_route
from agent_comms.comms import Comms
from agent_comms.native_package import verify_native_package
from agent_comms.owner_launch import RetainedOwnerLaunch
from original_owner_capture import CurrentTypedCapture
from original_turn_resource_real_installed_pilot import readonly_inputs
from runtime_fixture import stop_test_children

BASE=Path('/home/ts/wt/toad-workspace-warm-raster-followup-20260930')
SOURCE_BASE=Path('/home/ts/wt/toad-workspace-growing-end-continuity-20260930')
RUNTIME=BASE/'.artifacts/installed-bounded-admission-239/bin'
STAGE=SOURCE_BASE/'.artifacts/private-warm-scroll-236-01'
EVIDENCE=BASE/'.artifacts/bounded-admission-239-physical-attempt01'
NATIVE=Path('/home/ts/.local/share/agent-comms/native-current-e36a1dde326b7017/node_modules/@earendil-works/pi-coding-agent')
OUTPUT=Path('/home/ts/.cache/agent-scratch/toad-bounded-admission-239-20260930-attempt01')

async def main():
    EVIDENCE.mkdir(exist_ok=False)
    service=Comms(STAGE/'wire')
    sources=[service.registry.require(n) for n in ('resource436','resource236b')]
    assert all(not t.process_alive and t.active_turn is None for t in sources)
    readonly_inputs(service)
    copies=json.loads((SOURCE_BASE/'evidence/workspace-rendered-history-236/physical-source-capture/private-copy-hashes.json').read_text())
    import hashlib
    for row in copies:
        with Path(row['path']).open('rb') as stream:
            assert hashlib.file_digest(stream,'sha256').hexdigest()==row['sha256']
    route=read_active_route()
    assert route is not None
    observed=CurrentTypedCapture(root=route.root,original_python=RUNTIME/'python').observe('nra-architecture')
    snapshot=observed.document.snapshot()
    current=observed.selection.require_current(snapshot)
    launch=RetainedOwnerLaunch.capture(current,snapshot)
    capture=CurrentTypedCapture(root=route.root,original_python=Path(launch.interpreter)).read('nra-architecture')
    # Credentials are a current launch resource. The copied sources retain
    # their certified pre-cutover model/thinking; current public settings do
    # not own this independent snapshot and cannot invalidate its witness.
    print('CURRENT_ENV_RESOURCE_CAPTURED '+json.dumps({'current_model':capture.source.model,'current_thinking':capture.source.thinking_level.declared_name,'copied_model':sources[0].model,'copied_thinking':sources[0].thinking_level.declared_name}),flush=True)
    verify_native_package(NATIVE)
    env=dict(capture.retained.environment)
    with service.bus.log.locked():
        root_id=service.bus.log.read_metadata_unlocked(required=True).root_id
    service.owners.pin_private_nk_launch(service.root,root_id,NATIVE)
    env.update(AGENT_COMMS_ROOT=str(service.root),AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
        AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(NATIVE),AGENT_COMMS_RUNTIME_ROOT=str(RUNTIME),
        AGENT_COMMS_ACP_LAUNCHER=str(RUNTIME/'agent-comms-acp'),AGENT_COMMS_AGENT_BIN=str(RUNTIME/'pi-comms-native'),
        AGENT_COMMS_AGENT_ARGS=shlex.join(capture.retained.arguments or ()),
        PATH=str(RUNTIME)+os.pathsep+env.get('PATH',''),VIRTUAL_ENV=str(RUNTIME.parent),
        XDG_CONFIG_HOME=str(STAGE/'config'),XDG_DATA_HOME=str(STAGE/'data'),
        XDG_STATE_HOME=str(OUTPUT/'state'),TOAD_TEST_ATTEMPT=STAGE.name,
        AGENT_COMMS_DEBUG_LOG=str(STAGE/'acp-debug'))
    for key in ('PYTHONPATH','PI_PROMPT','PI_PARENT_ID','PI_TASK','PI_AGENT_ID','AGENT_COMMS_THREAD','AGENT_COMMS_STARTUP_INPUT_KEY'):
        env.pop(key,None)
    env.pop('NO_COLOR',None)
    receipt={'environment_capture':'CurrentTypedCapture447','original_snapshot_witness_already_released':True,
        'sources_reused_without_recopy':True,'public_process_not_held':True,'root':str(service.root),
        'runtime':str(RUNTIME),'output':str(OUTPUT),'input_count_before':0}
    (EVIDENCE/'current-environment-admission.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('CURRENT_PRIVATE_ENVIRONMENT_ADMITTED',flush=True)
    if sys.argv[1:]!=['--execute']:
        return
    argv=[str(RUNTIME/'python'),str(BASE/'tests/tools/physical_warm_capture.py'),
        '--project',str(STAGE/'project'),'--output',str(OUTPUT),'--session','resource436','--peer-thread','resource236b']
    try:
        # Canonical explicit start admits these already declared test owners.
        # No schema/registration edits and no startup input or inherited replay.
        from dataclasses import asdict
        os.environ.clear()
        os.environ.update(env)
        receipt['explicit_private_starts']=[asdict(service.owners.start(
            thread.name, agent_bin=str(RUNTIME/'pi-comms-native'),
            agent_args=capture.retained.arguments)) for thread in sources]
        readonly_inputs(service)
        (EVIDENCE/'owner-starts.json').write_text(json.dumps(receipt['explicit_private_starts'],indent=2)+'\n')
        child=await asyncio.create_subprocess_exec(*argv,env=env,cwd=STAGE/'project')
        status=await child.wait()
        receipt['driver_exit_code']=status
        readonly_inputs(service)
        assert status==0, f'Physical recorder exited {status}'
    finally:
        for owner in service.registry.all_threads().values():
            if owner.role.executable and owner.process_alive:
                await asyncio.to_thread(service.owners.stop,owner.name)
        await stop_test_children(STAGE.name)
        receipt['children_retired']=all(not t.process_alive for t in service.registry.all_threads().values())
        (EVIDENCE/'physical-adoption-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')

asyncio.run(main())
