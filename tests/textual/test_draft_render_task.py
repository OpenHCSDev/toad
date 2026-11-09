"""Textual-facing: a draft is parsed by a task a render worker can run, and growing keeps its rows."""

import pickle

from agent_comms.messaging.display_references import ProjectReferences
from agent_comms.transcript.transcript_events import AssistantTranscript
from textual.app import App

from toad.markdown_links import LinkContext
from toad.textual_colours import ThemedApp
from toad.widgets.transcript_fragments import (
    DraftBlocksRenderTask,
    FragmentPlan,
    transcript_fragments,
)
from toad.widgets.transcript_lines import (
    AcquiredRows,
    LinePreparation,
    RichLineRenderer,
    TranscriptLinesRenderTask,
)


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


def long_text(paragraphs):
    # Longer than one render budget, so the split that used to run on the UI thread runs too.
    return "\n\n".join(
        f"Paragraph {index} with `inline code` and **bold**.\n\n- first\n- second\n\n"
        "```python\ndef frame():\n    return 16\n```"
        for index in range(paragraphs)
    )


def source_blocks(text, theme):
    events = (AssistantTranscript(text, position=1, timestamp=0.0),)
    task = DraftBlocksRenderTask(FragmentPlan.read(events, resolve_sent=no_sent))
    return LinePreparation(pickle.loads(pickle.dumps(pickle.loads(pickle.dumps(task)).execute())), theme)


def test_a_draft_task_carried_to_a_worker_builds_what_its_fragments_build(tmp_path):
    text = long_text(12)
    theme = line_theme()
    context = LinkContext(tmp_path, ProjectReferences())
    built = transcript_fragments((AssistantTranscript(text, position=1, timestamp=0.0),), resolve_sent=no_sent)
    assert len(built) > 1
    blocks = tuple(block for fragment in built for block in fragment.line_blocks)
    direct = TranscriptLinesRenderTask(LinePreparation(blocks, theme), context).execute()

    carried = TranscriptLinesRenderTask(source_blocks(text, theme), context).execute()

    assert rows(carried, theme) == rows(direct, theme)
    assert any("Paragraph 11" in row for row in rows(carried, theme))


def test_a_growing_draft_keeps_what_it_already_styled(tmp_path):
    theme = line_theme()
    context = LinkContext(tmp_path, ProjectReferences())
    first = source_blocks(long_text(12), theme)
    styled = TranscriptLinesRenderTask(first, context).execute()
    drawn = AcquiredRows(first, styled.wrap(80, RichLineRenderer(theme)), context)

    grown = source_blocks(long_text(12) + "\n\nThe next paragraph, still arriving", theme)
    retained = drawn.retained_blocks(grown, context)

    # Only the end of the message is sent to be styled again.
    assert len(first.blocks) > 8
    assert len(retained) >= len(first.blocks) - 3
    assert all(retained[index] is styled.blocks[index] for index in range(len(first.blocks) - 3))
