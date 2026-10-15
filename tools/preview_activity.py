"""Opt-in one-row TTE comparison in the real saved-session frontend.

Use an existing runtime's Python on an approved isolated display. No installed
package changes or provider input. Normal status, clock and geometry owners
remain in charge. Only this process binds prepared effects to its existing bars.
"""
from __future__ import annotations

import fcntl
import functools
import json
import os
from pathlib import Path
import runpy
import sys
from dataclasses import replace


def main():
    root = Path(__file__).resolve().parents[1]
    out = Path('/home/ts/.cache/agent-scratch/toad-activity-disclosure/text-previews')
    out.mkdir(parents=True, exist_ok=True)
    runtime = Path(sys.executable).parent.parent
    lease = os.open(Path.home() / '.local/state/agent-comms', os.O_RDONLY)
    fcntl.flock(lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
    os.set_inheritable(lease, True)
    for key in ('AGENT_COMMS_ROOT', 'AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID',
                'AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE', 'PYTHONPATH',
                'AGENT_COMMS_THREAD', 'AGENT_COMMS_MANAGED', 'PI_AGENT_ID',
                'PI_PARENT_ID', 'PI_TASK', 'PI_WORKTREE', 'PI_PROMPT',
                'NO_COLOR', 'TOAD_VALIDATION'):
        os.environ.pop(key, None)
    sys.path[:0] = [str(root / 'src'), '/home/ts/wt/ui-theme-colours/src']

    from agent_comms.comms import wire
    from ui_theme.effects import LoopingText
    from ui_theme.scheme import MutedColour
    from ui_theme.splash import TextEffect
    from toad.render_tasks import TextEffectRenderTask
    from toad.widgets.conversation import ConversationSessionBinding
    from toad.widgets.session_details import SessionDetails
    from toad.widgets.throbber import Throbber
    import toad.textual_colours as colours
    import toad.transcript_publication as history
    import ui_theme.effects as effects

    # Bind through the actual owning relationships, never infer status identity
    # from a glyph, numeric thickness, descendant query or copied busy state.
    highlight = TextEffect('highlight', '━', (MutedColour,), 20, 4.0)
    beams = TextEffect('beams', '─', (MutedColour,), 20, 4.0)
    original_details = SessionDetails.__init__
    original_binding = ConversationSessionBinding.__init__

    @functools.wraps(original_details)
    def details_init(self, *args, **kwargs):
        original_details(self, *args, **kwargs)
        self.activity_bar._preview_text = highlight

    @functools.wraps(original_binding)
    def binding_init(self, *args, **kwargs):
        original_binding(self, *args, **kwargs)
        self.throbber._preview_text = beams

    SessionDetails.__init__ = details_init
    ConversationSessionBinding.__init__ = binding_init

    async def prepare_region(widget, width):
        scheme = widget.app.colours.scheme
        spec = widget._preview_text
        description = replace(spec, text=spec.text * width)
        # Existing reusable preparation executes TextEffect.build in its worker.
        played = await widget.app.prepare_background(TextEffectRenderTask(description, scheme))
        if (not widget.is_attached or widget.content_size.width != width
                or widget.app.colours.scheme is not scheme):
            return
        widget.stop_effect()
        widget.effect = LoopingText(played.frames, played.frames_per_second)
        widget.watch_busy(widget.busy)
        record = dict(effect=description.effect, glyph=spec.text,
                      width=width, scheme=scheme.name, frames=len(played.frames),
                      rows=sorted({len(frame.lines) for frame in played.frames}),
                      region=list(widget.region), pid=os.getpid(),
                      task='TextEffectRenderTask via app.prepare_background')
        with (out / 'prepared-regions.jsonl').open('a') as file:
            file.write(json.dumps(record) + '\n')

    def region_resized(self, event):
        width = self.content_size.width
        if width > 0:
            self.run_worker(prepare_region(self, width), group='activity-preview', exclusive=True)

    # Preparation responds to geometry, not status deltas or animation ticks.
    Throbber.on_resize = region_resized

    (out / 'source.json').write_text(json.dumps(dict(
        pid=os.getpid(), runtime=str(runtime), session='toad-theme',
        comparison='top Highlight / bottom Beams; installed design unchanged',
        modules={module.__name__:module.__file__ for module in (colours,history,effects)},
        rendering='existing TextualColours.paint_text -> Content.render_segments -> Strip',
        playback='existing Throbber/Animated/AnimationClock; prebuilt LoopingText',
    ), indent=2))
    project = wire().registry.require('toad-theme').worktree
    sys.argv = [str(runtime / 'bin/toad'), 'acp', f'{runtime}/bin/python -m agent_comms.acp',
                str(project), '--session', 'toad-theme', '--title', 'Agent Comms']
    runpy.run_path(str(runtime / 'bin/toad'), run_name='__main__')


if __name__ == '__main__':
    main()
