import asyncio,json,os
from pathlib import Path
from tempfile import TemporaryDirectory
import pyte
from textual._compositor import CompositorUpdate
from toad.app import ToadApp
from toad.widgets.prompt import QueueSummary

class App(ToadApp):
    CSS_PATH=Path(__import__("toad.app",fromlist=["__file__"]).__file__).parent / "toad.tcss"
    def __init__(self,*a,**kw):
        self.frames=[]
        self.terminal=pyte.Screen(120,35)
        self.stream=pyte.Stream(self.terminal)
        super().__init__(*a,**kw)
    def _display(self,screen,renderable):
        super()._display(screen,renderable)
        if self._batch_count or screen is not self.screen or not isinstance(renderable,CompositorUpdate):return
        ansi=renderable.render_segments(self.console)
        self.stream.feed(ansi)
        rows=[(i,row) for i,row in enumerate(self.terminal.display) if 'CAPTION_RESOURCE' in row]
        self.frames.append({'rows':rows,'ansi':ansi})

async def main():
    base=Path(os.environ.get('CAPTION_ARTIFACTS','.artifacts/caption-layout')).resolve()
    with TemporaryDirectory(dir=base) as directory:
        root=Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root/'config'),XDG_STATE_HOME=str(root/'state'),XDG_DATA_HOME=str(root/'data'),AGENT_COMMS_ROOT=str(root/'wire'))
        app=App(project_dir=str(root))
        async with app.run_test(size=(120,35)) as pilot:
            await app.selected_session.wait_content_ready()
            await pilot.pause(.3)
            view=app.selected_session.conversation
            view.agent_ready=True
            prompt=view.prompt
            label=prompt.query_one(QueueSummary)
            prompt.set_class(True,'-has-queue')
            label.update('Submitting (1): CAPTION_RESOURCE')
            await pilot.pause()
            print('initial',list(label.region),list(prompt.region),prompt.classes,app.frames[-1]['rows'])
            mark=len(app.frames)
            prompt.set_class(True,'-queue-mode')
            label.update('Queued (1): CAPTION_RESOURCE')
            if os.environ.get('READ_FULL_MAP'):
                _=app.screen._compositor.full_map
            await pilot.pause()
            rows=[f['rows'] for f in app.frames[mark:]]
            print('transition',list(label.region),rows)
            (base/os.environ.get('CAPTION_RECEIPT',('full-map' if os.environ.get('READ_FULL_MAP') else 'normal'))).with_suffix('.json').write_text(json.dumps(app.frames[mark:],indent=2))
            assert rows and all(len(r)==1 for r in rows),rows
        assert app._exception is None
asyncio.run(main())
