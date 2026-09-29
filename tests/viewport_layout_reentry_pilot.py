"""Installed native scroll ownership: defer paint without synchronous layout reentry."""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import Comms
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse


async def main():
    with TemporaryDirectory(dir='.artifacts', prefix='viewport-layout-') as folder:
        root=Path(folder).resolve()
        os.environ.update(AGENT_COMMS_ROOT=str(root/'wire'), XDG_STATE_HOME=str(root/'state'),
                          XDG_CONFIG_HOME=str(root/'config'), XDG_DATA_HOME=str(root/'data'))
        Comms(root/'wire').messaging.initialize_private_initial_protocol()
        app=ToadApp(project_dir=str(root))
        async with app.run_test(size=(139,25)) as pilot:
            await app.screen.wait_content_ready()
            await pilot.pause()
            screen=app.screen
            first_mode=app.current_mode
            view=screen.conversation
            response=await view.post(AgentResponse('\n\n'.join(f'Visible paragraph {i}' for i in range(45))))
            window=view.window
            window.anchor()
            await pilot.pause()
            assert window.max_scroll_y>0 and window.follows_tail
            # Observe the actual callbacks; all underlying Textual/Toad behavior runs.
            presentation=screen.viewport_presentation
            original_prepare=presentation.prepare
            original_layout=screen._refresh_layout
            depth=0
            peak=0
            nested_layouts=0
            def observe_prepare(wait):
                nonlocal depth,peak
                depth+=1;peak=max(peak,depth)
                try:return original_prepare(wait)
                finally:depth-=1
            def observe_layout(*args,**kwargs):
                nonlocal nested_layouts
                if depth:nested_layouts+=1
                return original_layout(*args,**kwargs)
            presentation.prepare=observe_prepare
            screen._refresh_layout=observe_layout
            # A native scroll setter leaves tail intent intact. Prepare must
            # reconcile this pending tail gap through native UpdateScroll.
            window.scroll_y=window.max_scroll_y-1
            screen._compositor_refresh()
            assert nested_layouts==0, ('synchronous layout from paint preparation',nested_layouts,peak)
            await pilot.pause()
            assert peak==1 and window.scroll_y==window.max_scroll_y
            for width,height in ((70,25),(139,25),(139,26),(139,25)):
                await pilot.resize_terminal(width,height)
                await response.append('\n\nGROWTH_MARKER visible live tail after resize.')
                await pilot.pause()
                assert window.follows_tail and window.scroll_y==window.max_scroll_y
            window.scroll_relative(y=-5,animate=False,immediate=True)
            await pilot.pause()
            position=window.scroll_y
            await response.append('\n\nAdditional output while reading.')
            await pilot.pause()
            assert not window.follows_tail and window.scroll_y==position
            window.scroll_end(animate=False,immediate=True)
            await pilot.pause()
            region=window.content_region
            frame='\n'.join(s.crop(region.x,region.right).text for s in screen._compositor.render_strips()[region.y:region.bottom])
            assert 'Additional output while reading' in frame, frame
            assert nested_layouts==0 and peak==1
            await app.new_session_screen(app.get_main_screen)
            await app.screen.wait_content_ready()
            await pilot.pause()
            await app.switch_mode(first_mode)
            await app.screen.wait_content_ready()
            await pilot.pause()
            assert app._exception is None
            print('PASS actual installed139x25: no synchronous reentry, growth+resize tail, reader position, cropped output paint, session switch/return')

if __name__=='__main__':asyncio.run(main())
