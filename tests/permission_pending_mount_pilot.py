"""Installed real Textual push, stopped immediately before its callback flush."""
import asyncio
import os
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from agent_comms.comms import Comms
from runtime_fixture import ToadApp
from toad.acp.agent import Agent
from toad.agent_schema import AgentDefinition
from toad.screens.permissions import PermissionsScreen
from textual.worker import get_current_worker, NoActiveWorker


async def main():
    ToadApp.CSS_PATH = files('toad').joinpath('toad.tcss')
    with TemporaryDirectory(dir='.artifacts') as directory:
        root=Path(directory).resolve()
        wire=Comms(root/'wire');wire.messaging.initialize_private_initial_protocol()
        os.environ.update(AGENT_COMMS_ROOT=str(wire.root),XDG_CONFIG_HOME=str(root/'config'),
                          XDG_DATA_HOME=str(root/'data'),XDG_STATE_HOME=str(root/'state'))
        app=ToadApp(project_dir=str(root))
        async with app.run_test(size=(120,40)) as pilot:
            await app.screen.wait_content_ready()
            view=app.selected_session.conversation
            agent=Agent(root,AgentDefinition.decode({'name':'RPC','identity':'fixture',
                'short_name':'fixture','run_command':{'*':'true'},'protocol':'acp'}),'session')
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
            app._flush_next_callbacks=actual_flush
            # The registered protocol reaches the original request and actual inline UI.
            # Repeated publication must reuse that binding's acquired Ask resource.
            task=asyncio.create_task(agent.server.call({'jsonrpc':'2.0','id':3,
                'method':'session/request_permission','params':{'sessionId':'session',
                'options':[{'optionId':'allow','name':'Allow inline','kind':'allow_once'}],
                'toolCall':{'toolCallId':'inline-original','kind':'read','title':'Inline original',
                            'content':[{'type':'content','content':{'type':'text','text':'Original inline preview'}}]}}}))
            async with asyncio.timeout(10):
                while view.prompt._ask is None:
                    await pilot.pause(.02)
            request,=agent.permissions.pending
            original_ask=view.prompt._ask
            original_binding=agent.controller.surface
            agent.permissions.present()
            await pilot.pause()
            assert view.prompt._ask is original_ask and not view.prompt.ask_queue
            assert request.owns_projection(original_binding,view)
            # Reattach the SAME native view: the old binding must not answer or
            # retire the replacement binding's original request resource.
            agent.detach_surface(view)
            view.bind_agent(agent)
            async with asyncio.timeout(10):
                while view.prompt._ask is None:
                    await pilot.pause(.02)
            assert view.prompt._ask is not original_ask
            request.answer(original_binding,request.options[0])
            assert request.pending
            assert request.owns_projection(agent.controller.surface,view)
            frame='\n'.join(strip.text for strip in app.screen._compositor.render_strips())
            assert 'Inline original' in frame and 'Allow inline' in frame
            app.save_screenshot(str(Path(os.environ.get('PERMISSION_EVIDENCE',root))/'inline.svg'))
            await pilot.press('enter')
            result=await task
            assert result['result']['outcome']=={'outcome':'selected','optionId':'allow'}
            await pilot.pause()
            assert view.prompt._ask is None and not view.prompt.ask_queue
            await agent.stop()
            await pilot.pause()
            loop.set_exception_handler(prior_handler)
            assert not errors, errors
    print('PASS installed App/registered ACP: pending modal cancellation, replacement diff paint/answer, duplicate inline publication, same-view reattach, retired binding refusal, exact original answer and cleanup')


if __name__=='__main__':asyncio.run(main())
