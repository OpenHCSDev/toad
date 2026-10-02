"""Compact message geometry and an independent, lazy right-hand thread sidebar."""

from agent_comms.transcript_events import IncomingTranscript

from agent_comms.message_reference import MessageReference
import asyncio
import os
import tempfile
from pathlib import Path
from agent_comms.routing import MessageRoute
from runtime_fixture import ToadApp
from toad.screens.main import MainScreen
from toad.response_delivery import ResponseDelivery
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.project_panel import ProjectPanel
from toad.widgets.route_header import RouteHeader
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SideBarToggle
from toad.widgets.tool_call import ToolCall
from toad.widgets.conversation import TurnActivity
from toad.core.events import CommsUpdated
from toad.core.events import ToolCall as ToolUpdate
from toad.acp.status import ToolCallStatus
from acp.schema import ToolCall as SDKToolCall
from agent_comms.acp_extension import TurnSettledUpdate, TurnStartedUpdate

async def main():
    with tempfile.TemporaryDirectory(prefix='toad-layout-') as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / 'config'), XDG_STATE_HOME=str(root / 'state'), XDG_DATA_HOME=str(root / 'data'), AGENT_COMMS_ROOT=str(root / 'wire'))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            screen = app.screen
            owner = app.selected_mode
            left = screen.query_one('#channels-sidebar', SideBar)
            right = screen.query_one('#thread-sidebar', SideBar)
            view = screen.conversation
            assert right.collapsed and (not screen.query(ProjectDirectoryTree)), (right.collapsed, right.hide, right._navigation, [(str(tree.path), str(tree.region)) for tree in screen.query(ProjectDirectoryTree)])
            assert right.region.x >= view.region.right
            controls = left.query_one('#sidebar-controls')
            assert controls.region.bottom == left.region.bottom
            assert left.query_one('#sidebar-panels').region.bottom == controls.region.y
            await pilot.click(right.query_one(SideBarToggle))
            await pilot.pause()
            assert not right.collapsed and (not left.collapsed)
            assert right.region.x >= view.region.right and right.region.x > left.region.right
            assert right.region.right == screen.size.width
            project = next((panel for panel in right.query(SideBarCollapsible) if panel.title == 'Project'))
            project.collapsed = False
            async with asyncio.timeout(5):
                while not screen.query(ProjectDirectoryTree):
                    await pilot.pause(0.05)
            assert screen.query_one(ProjectDirectoryTree).path == root
            other = await app.session_navigation.new(lambda: MainScreen(root / 'other'))
            await pilot.pause()
            assert app.screen.query_one('#thread-sidebar', SideBar).collapsed
            assert not app.screen.query(ProjectDirectoryTree)
            await app.switch_mode(owner)
            await pilot.pause()
            assert not right.collapsed
            await pilot.click(right.query_one(SideBarToggle))
            await pilot.pause()
            assert right.collapsed and (not left.collapsed)
            await view.contents.remove_children()
            thought = await view.post(AgentThought('First summary\n\nSecond summary\n\nThird summary'))
            tool = await view.post(ToolCall({'toolCallId': 't', 'title': 'Run tests', 'status': 'completed'}))
            await pilot.pause()
            paragraphs = list(thought.query('MarkdownParagraph'))
            assert all((b.region.y == a.region.bottom for a, b in zip(paragraphs, paragraphs[1:])))
            assert tool.region.y - paragraphs[-1].region.bottom == 1
            assert thought.max_scroll_y == 0
            await view.contents.remove_children()
            incoming = await view.post(IncomingMessage(IncomingTranscript("Identical body", route=MessageRoute("peer", ("#comms",)), source=MessageReference(1, "layout-inbound"))))
            outgoing = await view.post(AgentResponse("Identical body", delivery=ResponseDelivery.from_route(MessageRoute("me", ("#comms",)))))
            await pilot.pause()
            first, second = (incoming.query_one(RouteHeader), outgoing.query_one(RouteHeader))
            assert first.region.height == second.region.height == 1
            assert incoming.size.height == outgoing.size.height
            assert '[FROM] peer' in first.render().plain and '[TO] #comms' in second.render().plain
            assert not outgoing.styles.border.top[0]
            await view.contents.remove_children()
            long = await view.post(AgentThought('\n\n'.join((f'Summary {i}' for i in range(20)))))
            await pilot.pause()
            assert long.size.height >= 20 and long.max_scroll_y == 0
            view.post_message(CommsUpdated(TurnStartedUpdate('test-turn', started_at=None, activity=None, activity_detail=None)))
            view.agent.events.publish(ToolUpdate(ToolCallStatus.from_acp(SDKToolCall.model_validate({'toolCallId': 'running', 'title': 'Running tests', 'status': 'in_progress'}, strict=True))))
            await pilot.pause()
            activity = view.query_one(TurnActivity)
            assert activity.display and activity.render().plain == 'Running tests'
            assert activity.region.y >= view.window.region.bottom
            assert activity.region.bottom == view.query_one('#throbber').region.y, (activity.region, view.query_one('#throbber').region, view.query_one('#throbber').styles.offset, view.query_one('#prompt-stack').region)
            assert not view.contents.query(TurnActivity)
            view.post_message(CommsUpdated(TurnSettledUpdate('test-turn')))
            await pilot.pause()
            assert not activity.display
    print('layout: compact thoughts, single block gap, matching routes, independent right sidebar and lazy tree')
if __name__ == '__main__':
    asyncio.run(main())
