"""What a test observes about rows still coming from the render worker."""

from toad.widgets.transcript_lines import BlockLines


def awaits_styling(lines: BlockLines) -> bool:
    """Whether these rows are still to come from the render worker, as the rows themselves answer."""
    return bool(lines.unstyled(lines))
