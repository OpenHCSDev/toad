"""Textual-facing: changing which message categories show restyles only the affected blocks, never the whole conversation."""

from unittest.mock import patch

from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from agent_comms.ui_model.message_category import ThinkingCategory, all_categories


async def test_category_change_does_not_restyle_the_whole_conversation(workspace):
    async with workspace.app(size=(130, 43)) as ui:
        view = ui.conversation
        await view.contents.mount(*[
            cls(f"## Record {index}\n\n" + "A paragraph of ordinary text.\n\n" * 5)
            for index in range(30) for cls in (AgentResponse, AgentThought)
        ])
        await ui.step()
        app, _ = ui.textual
        with patch.object(app, "update_styles", wraps=app.update_styles) as styles:
            for _ in range(4):
                for selected in (all_categories() - {ThinkingCategory}, all_categories()):
                    view.visible_categories = selected
                    await ui.step()
            whole_view = sum(call.args == (view,) for call in styles.call_args_list)
        assert whole_view == 0, "Category change restyled unrelated descendants"
