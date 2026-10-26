"""Textual-facing: the command dialog. Toad passes Core's declared channel context through real command discovery."""
import pytest

from agent_comms.channel_targets import NoChannel, OneChannel, PerTargetChannels
from agent_comms.native_arguments import ConfiguredBinary
from toad import about
from toad.navigation_target import NavigationTarget
from toad.widgets.comms_sidebar import CommsSidebar


@pytest.mark.parametrize("selection", [
    NoChannel(), OneChannel("#team"), PerTargetChannels({"owner": ("#team",)}),
])
async def test_target_discovery_keeps_declared_channel_selection(workspace, selection):
    workspace.thread("owner", "team", title="Command target")
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        context = NavigationTarget.named("owner").menu_context(
            app.screen.query_one(CommsSidebar), channel=selection, mode_name=app.selected_mode)
        assert context.selected_targets == ("owner",)
        assert context.title == "owner"
        actions = await app.preparation.run_thread(context.available_actions)
        assert actions
        assert all(action.targets == ("owner",) for action in actions)
        channel_actions = [action for action in actions if action.declaration.channel_fields()]
        offered = {channel for action in channel_actions
                   for channel in action.channels.channels_for("owner")}
        assert offered == set(selection.channels_for("owner")) - {None}
        assert all(action.channels == selection for action in channel_actions)
        assert ConfiguredBinary().configured() in about.render(app)
