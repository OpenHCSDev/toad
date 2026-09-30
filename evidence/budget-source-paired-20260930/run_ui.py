"""Invoke the existing installed first-fork user journey, without UI/ACP mocks."""
import asyncio,json,os,sys,time
from pathlib import Path

def run():
    sys.dont_write_bytecode=True
    base=Path(__file__).parent
    stage=Path('/home/ts/.local/share/agent-comms/runtime-native-budget-source-resume-20260930')
    assert Path(sys.prefix)==stage
    activation=json.loads((stage/'activation.json').read_text())
    import toad,agent_comms
    assert Path(toad.__file__).is_relative_to(stage) and Path(agent_comms.__file__).is_relative_to(stage)
    tests=Path('/home/ts/wt/toad-provider-login-action-modal-20260930/tests')
    sys.path.insert(0,str(tests))
    for key in ('PYTHONPATH','AGENT_COMMS_ROOT','AGENT_COMMS_RUNTIME_ROOT','AGENT_COMMS_ACP_LAUNCHER','AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID','AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE','AGENT_COMMS_THREAD','AGENT_COMMS_MANAGED','PI_AGENT_ID','PI_PARENT_ID','PI_TASK','PI_WORKTREE','PI_PROMPT','FORK_NATIVE_TASK','FORK_DIALOG_EVIDENCE'):
     os.environ.pop(key,None)
    evidence=base/'u02-proof';evidence.mkdir(mode=0o700,exist_ok=False)
    os.environ.update(TMPDIR=str(base),L0A_EVIDENCE=str(evidence),AC_NATIVE_COPIED_PACKAGE=activation['native_package'],PATH=str(stage/'bin')+os.pathsep+os.environ['PATH'],PYTHONPATH=str(tests),TOAD_TEST_ATTEMPT='Einstein-g453e-u02')
    from first_fork_native_installed_pilot import main,InstalledApp,acceptance
    origin=time.monotonic()
    (evidence/'preflight.json').write_text(json.dumps({'stage':str(stage),'activation':activation,'toad':toad.__file__,'core':agent_comms.__file__,'existing_journey':'first_fork_native_installed_pilot.default_acceptance','fixture':str(base/'u02'),'ui':'Actual installed Toad application, Pilot clicks and committed compositor/SVG paint; no UI/ACP/native replacements','provider':'controlledlocalhost2POSTs','source_pythonpath':False,'public_inputs':0},indent=2)+'\n')
    code=0
    try:
     asyncio.run(asyncio.wait_for(main(app_type=InstalledApp,acceptance=acceptance,provider_request_budget=2,fixture_stage=base/'u02'),105))
    except BaseException:
     code=1;raise
    finally:
     (evidence/'terminal-receipt.json').write_text(json.dumps({'exit_code':code,'elapsed_seconds':time.monotonic()-origin,'paid_calls':0,'public_mutations':0,'manual_replays':0,'fixture_attempts':1},indent=2)+'\n')

if __name__ == "__main__":
    run()
