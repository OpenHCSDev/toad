"""Real Toad, no input: log each step of the sidebar target menu read."""
import faulthandler, json, os, signal, time
from pathlib import Path
from toad.cli import main
import toad.target_commands as tc
import toad.widgets.comms_menu as cm
OUT = Path('/home/ts/wt/toad-forms-migration/.scratch/p68-live') / os.environ['MENU_RUN']
OUT.mkdir(exist_ok=True)
faulthandler.register(signal.SIGUSR1, file=(OUT / 'stacks.txt').open('w'), all_threads=True)
log = (OUT / 'menu-steps.jsonl').open('a', buffering=1)
def note(step, **kw):
    log.write(json.dumps({'t': time.time(), 'step': step, **kw}) + '\n')
orig_show, orig_choices, orig_target = tc.TargetContext.show_menu, tc.TargetContext.command_choices, cm.show_target_menu
def show_menu(self, sidebar, offset):
    note('show_menu', subject=str(self.subject), comms=id(self.comms), sidebar_service=id(sidebar.service),
         selected=repr(sidebar.app.selected_session)[:120], screen=repr(sidebar.app.screen)[:120])
    return orig_show(self, sidebar, offset)
async def command_choices(self):
    note('choices-start')
    try:
        out = await orig_choices(self)
    except BaseException as e:
        note('choices-error', error=repr(e)); raise
    note('choices-done', n=len(out))
    return out
def show_target_menu(screen, *a, **k):
    note('show_target_menu', screen=repr(screen)[:120])
    return orig_target(screen, *a, **k)
tc.TargetContext.show_menu, tc.TargetContext.command_choices, cm.show_target_menu = show_menu, command_choices, show_target_menu
import textual.worker as _tw, traceback as _tb
_wf_init = _tw.WorkerFailed.__init__
def _wf(self, error):
    (OUT / 'worker-failed.txt').open('a').write(''.join(_tb.format_exception(error)) + '\n')
    _wf_init(self, error)
_tw.WorkerFailed.__init__ = _wf
import toad.transcript_source_preparation as _tsp
_pl = _tsp.TranscriptSourcePreparation._publish_latest
async def _publish_latest(self, current):
    before = [(repr(v.page)[:300], v.prepared.fragment_range) for v in self.pages]
    out = await _pl(self, current)
    note('publish_latest', cls=type(self).__name__, through=repr(self.through), result=out, before=before,
         after=[(repr(v.page)[:300], v.prepared.fragment_range) for v in self.pages])
    return out
_tsp.TranscriptSourcePreparation._publish_latest = _publish_latest
if __name__ == '__main__':
    main()
