from toad.conversation_turn import AgentTurn, ClientTurn
"""Session metadata occupies one collapsed row and a bounded, native disclosure."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.messages import Message, MessageType
from agent_comms.presentation import MessageNotification
from agent_comms.thread_presentation import ThreadPresentation
from textual.app import App
from textual.widgets import Input
from runtime_fixture import ToadApp

from toad.widgets.conversation import TurnActivity
from toad.widgets.input_delivery import InputDeliveryBar, empty_delivery
from toad.widgets.native_history import NativeHistory
from toad.widgets.session_details import SessionDetails


async def check_disclosure(ansi):
    notifications = tuple(MessageNotification(
        "owner", "Responded", "", message=Message("peer", "#comms", f"Receipt {index}: " + "body " * 30,
                                                 MessageType.INFO, seq=index + 1),
    ) for index in range(30))
    state = ThreadPresentation("owner", "●", "Ready", notifications=notifications)

    async def read():
        return state

    history = NativeHistory()
    history.status = "none"
    delivery = InputDeliveryBar()
    delivery.delivery = {**empty_delivery(), "dismissedHistoricalCount": 5}
    details = SessionDetails(read, history=history, delivery=delivery)

    class Example(App):
        def compose(self):
            yield details
            yield Input("Untouched draft", id="composer")

    app = Example(ansi_color=ansi)
    async with app.run_test(size=(90, 30)) as pilot:
        async with asyncio.timeout(5):
            while details.activity.presentation is None:
                await pilot.pause(.02)
        await pilot.pause()
        composer = app.query_one(Input)
        assert details.collapsed and details.size.height == 1
        frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert "Session details" in frame and "30 recent" in frame and "5 notices" in frame
        assert "Receipt 0" not in frame and "Bus history:" not in frame
        assert composer.region.y == details.region.bottom

        assert await pilot.click(details.query_one("CollapsibleTitle"))
        await pilot.pause()
        assert not details.collapsed and details.size.height <= details.DETAIL_ROWS + 1
        assert "Recent incoming messages" in str(details.activity.render())
        history.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
        assert history in app.screen._compositor.visible_widgets
        assert "no verified input" in str(history.render())
        details.collapsed = True
        delivery.error = "Could not read delivery state"
        await pilot.pause()
        assert details.size.height == 1 and details.has_class("-attention")
        assert "Delivery unavailable" in str(details.title)
        assert composer.value == "Untouched draft"
        assert details.activity.presentation is state and history.status == "none"
        assert delivery.delivery["dismissedHistoricalCount"] == 5
        assert app._exception is None


async def check_live_activity():
    with TemporaryDirectory(prefix="toad-session-details-activity-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            details = view.query_one(SessionDetails)
            activity = view.query_one(TurnActivity)
            view.native_history_status = "none"
            view.busy_count = 1
            view.turns.owner = AgentTurn()
            view.prompt.text = "Keep this unsent draft"
            for ansi, size in ((False, (100, 32)), (True, (76, 26))):
                app.ansi_color = ansi
                app.refresh_css()
                await pilot.resize_terminal(*size)
                for collapsed in (True, False):
                    details.collapsed = collapsed
                    for status in ("Thinking…", "Writing response…", "Calling tool: read"):
                        view.activity = status
                        await pilot.pause()
                        assert activity.region.bottom <= details.region.y, (
                            "Live activity must precede metadata, not be displaced by its divider", ansi)
                        assert activity in app.screen._compositor.visible_widgets
                        strips = app.screen._compositor.render_strips()
                        row = strips[activity.region.y].text[activity.region.x:activity.region.right]
                        assert status in row, (ansi, collapsed, row)
                        assert not details.styles.border_top[0], (ansi, collapsed, details.styles.border_top)
                        if collapsed:
                            assert details.size.height == 1
                        assert activity.region.bottom <= view.throbber.region.y
                        assert view.prompt.text == "Keep this unsent draft"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()


async def main():
    for ansi in (False, True):
        await check_disclosure(ansi)
    await check_live_activity()
    print("session details: one row in RGB/ANSI, bounded disclosure, live activity above details, draft intact")


if __name__ == "__main__":
    asyncio.run(main())
