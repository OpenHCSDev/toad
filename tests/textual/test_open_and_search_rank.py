"""`--open NAME` opens that conversation once the launch's tabs are back, as its sidebar row does;
the sidebar search lists the name typed exactly above the names it is a prefix of."""

from functools import partial

from toad.app import ToadApp
from toad.launch_opening import LaunchOpening, OpensTarget


def test_open_is_read_from_the_launch_and_removed():
    arguments = ["--open", "#source", "project", "--", "child", "--open", "other"]
    assert LaunchOpening.startup(arguments) == OpensTarget("#source")
    assert arguments == ["project", "--", "child", "--open", "other"]


async def test_launch_opens_the_named_channel(workspace):
    me = workspace.project.name
    workspace.thread(me, "source", running=True)
    workspace.comms.messaging.send(me, "#source", "Opened by the launch")
    launched = partial(ToadApp, opening=OpensTarget("#source"))
    async with workspace.app(size=(100, 40), application=launched, session=False) as ui:
        await ui.until_shows("Opened by the launch")


async def test_search_lists_the_exact_name_first(workspace):
    from toad.widgets.comms_sidebar import CommsSidebar

    for name in ("claude-a", "claude-ab12", "claude-ac34"):  # newest first: claude-a lists last
        workspace.thread(name, "lab", running=True)
    async with workspace.app(size=(120, 40)) as ui:
        app, _pilot = ui.textual
        sidebar = await ui.revealed(app.workspace_chrome.channels)
        tree = app.screen.query_one(CommsSidebar)
        await ui.until(lambda: tree.navigation.ready.is_set(), why="the channels sidebar's rows")
        sidebar.search = "claude-a"
        await ui.step()

        def listed():
            return [key for group in tree.navigation_groups for key in group.matching_keys]

        await ui.until(lambda: {"claude-a", "claude-ab12", "claude-ac34"} <= set(listed()),
                       why="every claude-a thread listed under the search")
        model_order = [key for group in tree.navigation_groups for key in group.member_keys
                       if key.startswith("claude-a")]
        assert model_order[0] != "claude-a", model_order  # the model alone would not list it first
        assert listed()[0] == "claude-a", listed()
