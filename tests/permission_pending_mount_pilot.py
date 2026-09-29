"""Installed real Textual push, stopped immediately before its callback flush."""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from agent_comms.comms import Comms
from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.screens.permissions import PermissionsScreen
from textual.worker import get_current_worker, NoActiveWorker


async def main():
    with TemporaryDirectory(dir='.artifacts') as directory:
        root=Path(directory).resolve()
        wire=Comms(root/'wire');wire.messaging.initialize_private_initial_protocol()
        os.environ.update(AGENT_COMMS_ROOT=str(wire.root),XDG_CONFIG_HOME=str(root/'config'),
                          XDG_DATA_HOME=str(root/'data'),XDG_STATE_HOME=str(root/'state'))
        app=ToadApp(project_dir=str(root))
        async with app.run_test(size=(120,40)) as pilot:
            await app.screen.wait_content_ready()
            view=app.selected_session.conversation
            agent=Agent(root,{'name':'RPC','run_command':{'*':'true'}},'session')
            view.agent=agent
            await pilot.pause()
            errors=[]
            loop=asyncio.get_running_loop()
            prior_handler=loop.get_exception_handler()
            loop.set_exception_handler(lambda loop, context: errors.append(context))
            from toad.widgets.conversation import Conversation
            actual_flush=app._flush_next_callbacks
            for outcome in ('cancel','replace'):
                entered,release=asyncio.Event(),asyncio.Event()
                original=view
                async def gated_flush():
                    try: worker=get_current_worker()
                    except NoActiveWorker: worker=None
                    if worker is not None and worker.name=='request_permissions' and worker.node is original:
                        entered.set()
                        await release.wait()
                    await actual_flush()
                app._flush_next_callbacks=gated_flush
                task=asyncio.create_task(agent.server.call({'jsonrpc':'2.0','id':1,
                    'method':'session/request_permission','params':{'sessionId':'session',
                    'options':[{'optionId':'allow','name':'Allow','kind':'allow_once'}],
                    'toolCall':{'toolCallId':'race-'+outcome,'kind':'edit','title':'Pending review',
                                'content':[{'type':'diff','path':str(root/'test.txt'),
                                            'oldText':'old visible value','newText':'new visible value'}]}}}))
                await entered.wait()
                request,=agent.permissions.pending
                workers=[w for w in view.workers if w.node is original and w.name=='request_permissions']
                assert not isinstance(app.screen,PermissionsScreen)
                if outcome=='cancel':
                    completed_callbacks=asyncio.Event()
                    request.future.add_done_callback(lambda future: completed_callbacks.set())
                    request.cancel()
                    await completed_callbacks.wait()
                else:
                    agent.detach_surface(original)
                    replacement=Conversation(root)
                    await original.parent.mount(replacement)
                    replacement.agent=agent
                    await pilot.pause()
                    assert request.pending and agent.controller.surface.owns(replacement)
                    view=replacement
                release.set()
                for worker in workers: await worker.wait()
                await pilot.pause()
                if outcome=='cancel':
                    result=await task
                    assert result['result']['outcome']=={'outcome':'cancelled'}
                    assert not isinstance(app.screen,PermissionsScreen)
                else:
                    assert isinstance(app.screen,PermissionsScreen)
                    frame='\n'.join(strip.text for strip in app.screen._compositor.render_strips())
                    assert 'visible value' in frame and 'Allow' in frame
                    await pilot.press('enter')
                    result=await task
                    assert result['result']['outcome']=={'outcome':'selected','optionId':'allow'}
                    await original.remove()
                    await pilot.pause()
                    assert not isinstance(app.screen,PermissionsScreen)
                assert app._exception is None
            await agent.stop()
            await pilot.pause()
            loop.set_exception_handler(prior_handler)
            assert not errors, errors
    print('PASS installed Textual pending modal mount: cancelled and replaced sources retire pending screen/worker; replacement request paints and grants')


if __name__=='__main__':asyncio.run(main())
