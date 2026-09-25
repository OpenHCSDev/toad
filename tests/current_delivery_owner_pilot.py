"""Mounted delivery controls use a real owner's queued-input and notice projection."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from delivery_owner_fixture import queued_delivery_owner
from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Static

from toad.widgets.input_delivery import InputDeliveryBar, InputDeliveryDetails


async def main():
    os.environ.pop("PI_AGENT_ID", None)
    os.environ.pop("AGENT_COMMS_THREAD", None)
    os.environ["AGENT_COMMS_AGENT_MODELS"] = "test/model"
    with TemporaryDirectory(prefix="delivery-current-ui-", dir="/var/tmp") as temporary:
        async with queued_delivery_owner(Path(temporary)) as (
            owner,
            proxy,
            session,
            incoming,
        ):
            snapshot = await proxy.request("input_dispositions")
            before = owner._dispositions._read()

            class DeliveryApp(App):
                def compose(self) -> ComposeResult:
                    yield InputDeliveryBar()

                async def refresh_delivery(self):
                    state = await proxy.request("input_dispositions")
                    self.screen_stack[0].query_one(InputDeliveryBar).delivery = state
                    if isinstance(self.screen, InputDeliveryDetails):
                        self.screen.delivery = state

                @on(InputDeliveryBar.Inspect)
                async def inspect(self):
                    async def load():
                        result = await proxy.request(
                            "input_dispositions", include_history=True
                        )
                        return result["historicalInputs"]

                    async def clear():
                        await proxy.request("dismiss_historical_inputs")
                        await self.refresh_delivery()

                    modal = InputDeliveryDetails(
                        log_path=None, load_history=load, dismiss_history=clear
                    )
                    modal.delivery = await proxy.request("input_dispositions")
                    self.push_screen(modal)

            app = DeliveryApp()
            async with app.run_test(size=(100, 32)) as pilot:
                bar = app.query_one(InputDeliveryBar)
                bar.delivery = snapshot
                await pilot.pause()
                assert "1 awaiting start" in str(
                    bar.query_one("#delivery-summary", Static).render()
                )
                assert "2 earlier notices" in str(
                    bar.query_one("#delivery-history-summary", Static).render()
                )
                await pilot.click("#delivery-inspect")
                await pilot.pause()
                details = app.screen
                assert isinstance(details, InputDeliveryDetails)
                # A new input is queued while the inspector is open. Clear must
                # use the owner's current queue, not the screen's earlier snapshot.
                second = owner._comms.send_message(
                    "peer", session, "Queued after opening inspector"
                )
                await owner._drain_inbox(session)
                details.query_one("#delivery-clear-history").scroll_visible(
                    immediate=True
                )
                details.query_one("#delivery-clear-history").focus()
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                state = await proxy.request("input_dispositions")
                assert [row["sequence"] for row in state["inputs"]] == [
                    incoming.seq,
                    second.seq,
                ]
                assert (
                    state["historicalCount"] == 0
                    and state["dismissedHistoricalCount"] == 2
                )
                assert all(
                    not owner._dispositions.get(f"bus:{seq}").get("notice_dismissed")
                    for seq in (incoming.seq, second.seq)
                )
                details.query_one("#delivery-load-history").scroll_visible(
                    immediate=True
                )
                details.query_one("#delivery-load-history").focus()
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                assert len(details._historical_inputs) == 2
                assert all(row["noticeDismissed"] for row in details._historical_inputs)
                assert "Notice cleared." in str(
                    details.query_one("#delivery-historical-records", Static).render()
                )
                for key, row in before.items():
                    assert all(
                        owner._dispositions.get(key)[field] == value
                        for field, value in row.items()
                    )
                assert not owner._backend_inboxes
                # The bar retains an inspector entry even when only cleared
                # notices remain, so clearing never makes evidence inaccessible.
                await pilot.press("escape")
                await pilot.pause()
                bar.delivery = {**state, "inputs": []}
                await pilot.pause()
                assert bar.display and bar.query_one("#delivery-inspect").display
                assert "2 earlier notices cleared" in str(
                    bar.query_one("#delivery-history-summary", Static).render()
                )
    print(
        "current delivery: real owner queue, mounted clear, new pending input, retained evidence passed"
    )


if __name__ == "__main__":
    asyncio.run(main())
