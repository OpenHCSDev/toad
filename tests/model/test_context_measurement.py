"""One context measurement says whether usage is known, where it came from and how it reads."""
from agent_comms.context_reading import ContextUsage, UnmeasuredContext
from toad.acp.context_measurement import ContextMeasurement, Cost
from rich.text import Text as RichText


def test_measurement_availability_source_and_status_text():
    unknown = ContextMeasurement.saved(UnmeasuredContext())
    assert 'Native owner has not reported' in unknown.status().plain
    for used, size in ((0, 272000), (120, 0), (-1, 120)):
        assert ContextMeasurement.live(used, size, None) == unknown
    live = ContextMeasurement.live(38723, 272000, Cost(.5, 'USD'))
    assert live.percentage_display == '14.2%'
    assert 'last response' not in live.status().plain
    saved = ContextMeasurement.saved(ContextUsage(38723, 272000))
    assert saved.status().plain == '38,723/272,000 tokens (14.2%)'
    rendered = live.status()
    assert isinstance(rendered, RichText)
    assert rendered.spans and all(span.style == 'bold' for span in rendered.spans)
    rendered.append(' native-only decoration')
    assert 'decoration' not in live.status().plain
