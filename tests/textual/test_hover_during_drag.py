"""Textual-facing: dragging a selection within one hovered text widget does not restyle the stylesheet on every pointer step."""

from unittest.mock import patch

from textual import events
from textual.geometry import Offset

from toad.widgets.agent_response import AgentResponse


async def test_pointer_steps_inside_one_widget_cause_no_restyle(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        app, pilot = ui.textual
        response = await ui.conversation.post(AgentResponse("Select this phrase " * 25))
        await ui.step()
        text = response.body
        await pilot.mouse_down(text, offset=(1, 0))
        screen = app.screen
        x, y = text.region.x + 3, text.region.y
        app.mouse_position = Offset(x, y)
        screen._forward_event(events.MouseMove(None, x, y, 2, 0, 1, False, False, False))
        assert app.mouse_over is not None
        previous_hover = app.hover_over
        with patch.object(app.stylesheet, "update_nodes", wraps=app.stylesheet.update_nodes) as restyle:
            for index in range(4, 10):
                x = text.region.x + index
                app.mouse_position = Offset(x, y)
                screen._forward_event(events.MouseMove(None, x, y, 1, 0, 1, False, False, False))
            assert app.hover_over is previous_hover and restyle.call_count == 0
        await pilot.mouse_up(text, offset=(10, 0))
        assert screen.get_selected_text()
