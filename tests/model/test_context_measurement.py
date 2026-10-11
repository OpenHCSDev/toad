"""One context measurement says whether usage is known, where it came from and how it reads."""
from toad.acp.context_measurement import ContextMeasurement, ContextUnavailable, Cost
from rich.text import Text as RichText


def test_measurement_availability_source_and_status_text():
    unknown = ContextMeasurement.saved(None)
    assert not unknown.available and 'Native owner has not reported' in unknown.status().plain
    for used, size in ((0, 272000), (120, 0), (-1, 120)):
        unknown = ContextMeasurement.live(used, size, None)
        assert not unknown.available
        assert '%' not in unknown.status().plain
    live = ContextMeasurement.live(38723, 272000, Cost(.5, 'USD'))
    assert live.percentage_display == '14.2%'
    assert 'last response' not in live.status().plain
    from agent_comms.acp_extension import ContextUsage
    saved = ContextMeasurement.saved(ContextUsage(38723, 272000))
    assert saved.used == live.used and saved.size == live.size
    assert 'last response' in saved.status().plain
    assert 'invalidated by compaction' in ContextUnavailable('Context measurement invalidated by compaction').status().plain
    rendered = live.status()
    assert isinstance(rendered, RichText)
    assert rendered.spans and all(span.style == 'bold' for span in rendered.spans)
    rendered.append(' native-only decoration')
    assert 'decoration' not in live.status().plain
