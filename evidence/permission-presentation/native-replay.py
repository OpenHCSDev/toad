import asyncio, importlib.util, os, sys, threading
from pathlib import Path
from agent_comms.acp import CommsAgent
from agent_comms.comms import Comms
from agent_comms.runtime import RuntimeProxy
from agent_comms.acp_extension import McpClientReceiptUpdate, TurnSettledUpdate, decode_updates
sys.path.insert(0,str(Path('tests').resolve()))
from native_permission_ui import open_observer
# Reuse the existing core MCP SDK/loopback fixture; only test import/routes change.
import types
source=Path('/home/ts/.agent-comms/tests/test_mcp_acceptance.py').read_text()
source=source.replace('from agent_comms.operations import wire','from agent_comms.comms import wire')
source=source.replace('PACKAGE = Path(__file__).resolve().parents[1] / "extensions" / "pi-mcp-client"',
    'PACKAGE = Path("/home/ts/.local/share/agent-comms/native-current-5fdef596596173bd/node_modules/@earendil-works/pi-coding-agent/agent-comms-extensions/pi-mcp-client")')
source=source.replace('api = PACKAGE / "node_modules/@earendil-works/pi-coding-agent/dist/index.js"',
    'api = Path("/home/ts/.local/share/agent-comms/native-current-5fdef596596173bd/node_modules/@earendil-works/pi-coding-agent/dist/index.js")')
f=types.ModuleType('native_helpers')
f.__file__='/home/ts/.agent-comms/tests/test_mcp_acceptance.py'
exec(compile(source,f.__file__,'exec'),f.__dict__)
package=Path('/home/ts/.local/share/agent-comms/native-current-5fdef596596173bd/node_modules/@earendil-works/pi-coding-agent')
import tempfile
owned=tempfile.TemporaryDirectory(prefix='native-permission-',dir='.artifacts')
root=Path(owned.name).resolve()
async def main():
    node,config,project,digest,starts,calls,env=f._prepare(root)
    seen,second,final=(threading.Event() for _ in range(3));final.set()
    comms=Comms(root/'wire');identity=comms.messaging.initialize_private_initial_protocol()
    settled=asyncio.Event()
    async with open_observer('allow',root) as observer:
        with f._mock_model(root,config,seen,second,final) as (requests,errors,guard):
            env.update(OPENROUTER_API_KEY='offline-fixture-no-real-key',NODE_OPTIONS=f'--require={guard}',
                       AGENT_COMMS_ROOT=str(comms.root),AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=identity,
                       AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),AC_MCP_RETIRE_SURFACE='1')
            original=dict(os.environ);os.environ.clear();os.environ.update(env)
            owner=CommsAgent(comms,agent_bin='pi',
                agent_args=['--offline','--no-extensions','--no-skills','--no-context-files','--no-builtin-tools',
                            '--provider','openrouter','--model','z-ai/glm-5.3-flash','--thinking','off','-e',str(f.PACKAGE)],
                runtime_enabled=True,auto_wake=False,private_nk_native_package=package,private_nk_wire_root_id=identity)
            attachment=CommsAgent(comms,auto_wake=False)
            class Client:
                async def session_update(self,session_id,update):
                    for fact in decode_updates(update.get('_meta')):
                        if isinstance(fact,McpClientReceiptUpdate):seen.set()
                        if isinstance(fact,TurnSettledUpdate):settled.set()
                    await observer.session_update(session_id,update)
                async def request_permission(self,**kwargs):
                    return await observer.request_permission(**kwargs)
            attachment.on_connect(Client());proxy=None
            try:
                session=(await owner.new_session(cwd=str(project),mcp_servers=[])).session_id
                assert session=='project'
                proxy=RuntimeProxy(attachment,session,owner._runtime.path)
                await proxy.subscribe();settled.clear()
                result=await asyncio.wait_for(proxy.request('prompt',prompt=[{'type':'text','text':'Run fixture echo once.'}]),60)
                await asyncio.wait_for(settled.wait(),5)
                assert result['stopReason']=='end_turn'
                assert len(requests)==2 and not errors, (requests,errors)
                assert calls.read_text().splitlines()==['ACCEPTANCE_ECHO']
                assert observer.permissions==1 and observer.permission_presented.is_set()
                print('PASS physical installed Pi + MCP + actual RuntimeServer/proxy + mounted permission options painted, surface retirement/rebinding and granted execution; loopback only')
            finally:
                seen.set();final.set()
                if proxy:await proxy.close()
                await owner.shutdown();await attachment.shutdown()
                os.environ.clear();os.environ.update(original)
if __name__=='__main__':
    asyncio.run(main())
    import psutil
    assert all(not psutil.pid_exists(int(pid)) for pid in (root/'server-starts').read_text().splitlines())
    print('native MCP child cleanup verified; no provider or live installation changes')
    owned.cleanup()
