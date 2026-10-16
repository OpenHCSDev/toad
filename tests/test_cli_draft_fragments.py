"""Live CLI items use the same tool fragments and reader choices as history."""
from agent_comms.external_transcript import ExternalDraftRow
from agent_comms.transcript_events import ToolStartTranscript
from toad.line_blocks import ToggleDetails
from toad.widgets.cli_draft import CliDraft
from toad.widgets.transcript_fragments import ToolTranscriptFragment, Shown, transcript_fragments


def draft(item='tool', command='printf prefix'):
    return ExternalDraftRow('thread', 'turn', item, (ToolStartTranscript(
        tool_call_id=item, tool_name='bash', raw_input={'command': command}),))


def test_live_tool_uses_normal_tool_fragment_before_any_result():
    fragment, = transcript_fragments(draft().events)
    assert isinstance(fragment, ToolTranscriptFragment)
    assert 'printf prefix' in fragment.tool_call.title
    assert any('printf prefix' in block.selection_text for block in fragment.blocks(Shown()))


def test_live_item_keeps_reader_choice_until_its_identity_changes():
    view = CliDraft()
    view.show(draft())
    view.action_open(ToggleDetails())
    assert view.shown.details_open
    view.show(draft(command='updated preview'))
    assert view.shown.details_open
    view.show(draft(item='next'))
    assert not view.shown.details_open
    view.action_open(ToggleDetails())
    view.show(None)
    assert not view.shown.details_open and not view.display
