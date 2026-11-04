"""A width-constrained conversation sits on the left, in the centre or on the right of its session contents, as the column setting says."""

import pytest

from toad.preferences import SETTINGS
from toad.setting_choices import CenterColumnAlignment, ColumnAlignment, LeftColumnAlignment, RightColumnAlignment


@pytest.mark.parametrize("alignment", ColumnAlignment.members_with(ColumnAlignment))
async def test_the_conversation_column_sits_where_its_alignment_says(workspace, alignment):
    async with workspace.app(size=(140, 40)) as ui:
        app, pilot = ui.textual
        settings = app.saved_settings
        settings.set(SETTINGS.ui.column, True)
        settings.set(SETTINGS.ui.column_width, 60)
        settings.set(SETTINGS.ui.column_alignment, alignment)
        for _ in range(3):
            await pilot.pause()
        conversation = ui.conversation
        contents, column = conversation.parent.region, conversation.region
        offset = {LeftColumnAlignment: 0, CenterColumnAlignment: (contents.width - 60) // 2,
                  RightColumnAlignment: contents.width - 60}[alignment]
        assert column.width == 60, (contents, column)
        assert column.x == contents.x + offset, (alignment, contents, column)
