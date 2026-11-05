"""Textual-facing: a draft's rows come from a task a render worker can run, parse included."""

import pickle

from agent_comms.display_references import ProjectReferences
from agent_comms.transcript_events import AssistantTranscript
from textual.app import App

from toad.markdown_links import LinkContext
from toad.textual_colours import ThemedApp
from toad.widgets.transcript_fragments import DraftLinesRenderTask, FragmentPlan, transcript_fragments
from toad.widgets.transcript_lines import LinePreparation, RichLineRenderer, TranscriptLinesRenderTask


class DraftApp(ThemedApp, App):
    pass


def line_theme():
    app = DraftApp()
    app.get_css_variables()
    return app.colours.line_theme


def rows(prepared, theme):
    return ["".join(segment.text for segment in row) for row in prepared.wrap(80, RichLineRenderer(theme))]


def no_sent(reports):
    return {}


def test_a_draft_task_carried_to_a_worker_draws_what_its_fragments_draw(tmp_path):
    # Longer than one render budget, so the split that used to run on the UI thread runs too.
    text = "\n\n".join(
        f"Paragraph {index} with `inline code` and **bold**.\n\n- first\n- second\n\n"
        "```python\ndef frame():\n    return 16\n```"
        for index in range(12)
    )
    events = (AssistantTranscript(text, position=1, timestamp=0.0),)
    theme = line_theme()
    context = LinkContext(tmp_path, ProjectReferences())
    built = transcript_fragments(events, resolve_sent=no_sent)
    assert len(built) > 1
    blocks = tuple(block for fragment in built for block in fragment.line_blocks)
    direct = TranscriptLinesRenderTask(LinePreparation(blocks, theme), context).execute()

    task = DraftLinesRenderTask(
        LinePreparation((), theme), context, FragmentPlan.read(events, resolve_sent=no_sent),
    )
    carried = pickle.loads(pickle.dumps(task))

    assert rows(carried.execute(), theme) == rows(direct, theme)
    assert any("Paragraph 11" in row for row in rows(carried.execute(), theme))
