"""The navigation column paints from its own placement, not from the compositor's map.

A frame that places no part of this one-column container leaves it out of the arranged map;
asking that map for the column's origin then raised `KeyError: CursorContainer()` in
`render_lines` (Toad log `KeyError_2026-11-07T15_52_49`) instead of painting the rail.
"""

from textual.geometry import Region

from toad.widgets.conversation import CursorContainer


async def test_the_column_paints_when_the_compositor_left_it_out(workspace):
    async with workspace.app(size=(90, 24)) as ui:
        await ui.new_session()
        container = next(iter(ui.app.screen.query(CursorContainer)))
        # Placed clear of the screen: no crop of this column in the arranged map.
        container.styles.offset = (-40, 0)
        await ui.step()
        compositor = container.screen._compositor
        assert container not in compositor.visible_widgets, (
            'the frame under test must be one the compositor left out'
        )
        strips = container.render_lines(Region(0, 0, 1, 3))
        assert len(strips) == 3
