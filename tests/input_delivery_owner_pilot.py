"""Real owner snapshots distinguish current delivery from dismissible legacy notices."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.acp import CommsAgent
from agent_comms.input_disposition import AcpDeliveryCursors
from agent_comms.operations import wire
from agent_comms.runtime import RuntimeProxy, socket_path
from textual.widgets import Static

from toad.acp.agent import Agent
from toad.app import ToadApp
from toad.widgets.input_delivery import (
    DeliveryHistoryAction,
    DeliveryInspect,
    InputDeliveryBar,
    InputDeliveryDetails,
)


async def main():
    with TemporaryDirectory(prefix="toad-delivery-owner-", dir="/var/tmp") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
            AGENT_COMMS_AGENT_MODELS="openrouter/fake",
        )
        comms = wire(root / "wire")
        project = root / "project"
        project.mkdir()
        AcpDeliveryCursors(comms.root).initialize(
            frozenset({"project"}),
            "project",
            high_water=932,
            fresh=False,
        )
        owner = CommsAgent(
            comms,
            agent_bin="pi",
            agent_args=["--provider", "openrouter", "--model", "fake"],
            runtime_enabled=True,
            auto_wake=False,
        )
        owner._ensure_live_drain = lambda _: None
        proxy = None
        try:
            session = (await owner.new_session(cwd=str(project))).session_id
            store = owner._dispositions
            admission = comms.registry.snapshot().admission_generations[session]
            old_rows = {
                f"bus:{sequence}": {
                    "key": f"bus:{sequence}",
                    "sequence": sequence,
                    "owner": session,
                    "admission": admission,
                    "target": "#review",
                    "source_text": f"Historical notice {sequence}: " + "x" * 880,
                    "turn_id": None,
                    "native_id": None,
                    "sent_text": None,
                    "status": "unknown",
                }
                for sequence in range(1, 933)
            }
            store._write(old_rows)
            store.record(
                "bus:933",
                seq=933,
                owner=session,
                admission=admission,
                target="#review",
                text="Please inspect [this] exact change",
            )
            store.record(
                "bus:934",
                seq=934,
                owner="another-owner",
                admission=1,
                target="#review",
                text="Not this owner",
            )
            agent = Agent(
                project, {"name": "agent-comms", "run_command": {"*": "true"}}, None
            )
            agent._coordination_root = str(comms.root)
            agent._coordination_thread = session
            owner_requests = []
            real_request = agent._owner_request

            async def observed_request(method, **params):
                owner_requests.append((method, params))
                return await real_request(method, **params)

            agent._owner_request = observed_request
            app = ToadApp(project_dir=str(project))
            async with app.run_test(size=(110, 35)) as pilot:
                app.theme = "textual-dark"
                await pilot.pause()
                conversation = app.screen.conversation
                conversation.set_reactive(type(conversation).agent, agent)
                agent.post_message = conversation.post_message

                class Subscriber:
                    async def session_update(self, *, session_id, update):
                        agent.rpc_session_update(session_id, update)

                observer = CommsAgent(comms)
                observer.on_connect(Subscriber())
                proxy = RuntimeProxy(
                    observer, session, socket_path(comms.root, os.getpid())
                )
                metadata = await proxy.subscribe()
                agent._publish_coordination_metadata({"_meta": metadata}, initial=True)
                await conversation.refresh_input_dispositions()
                await pilot.pause()
                rows = await agent.get_unresolved_inputs()
                assert len(rows) == 1 and rows[0]["sequence"] == 933
                assert conversation.unresolved_inputs == rows
                assert conversation.input_delivery["historicalCount"] == 932
                assert conversation.input_delivery["historicalInputs"] == []
                bar = conversation.query_one(InputDeliveryBar)
                assert bar.display
                assert (
                    str(bar.query_one("#delivery-summary", Static).render())
                    == "Delivery · 1 unconfirmed"
                )
                assert "932 historical notices" in str(
                    bar.query_one("#delivery-history-summary", Static).render()
                )
                app.save_screenshot(
                    filename="toad-delivery-overview.svg", path="/var/tmp"
                )
                await pilot.resize_terminal(65, 22)
                await pilot.pause()
                action = bar.query_one("#delivery-inspect", DeliveryInspect)
                assert action.content_size.width >= len("Inspect")
                assert action.content_size.height == 1
                assert action.region.bottom <= bar.region.bottom
                assert "Inspect" in "\n".join(
                    strip.text for strip in app.screen._compositor.render_strips()
                )
                action.focus()
                await pilot.press("enter")
                await pilot.pause()
                assert isinstance(app.screen, InputDeliveryDetails)
                await pilot.press("escape")
                await pilot.resize_terminal(110, 35)
                await pilot.pause()
                await pilot.click("#delivery-inspect")
                await pilot.pause()
                details = app.screen
                assert isinstance(details, InputDeliveryDetails)
                records = details.query_one("#delivery-records", Static)
                assert "Sequence: 933 · Target: #review" in str(records.render())
                assert "Please inspect [this] exact change" in str(records.render())
                assert details.query_one("#delivery-log")
                assert "not proof" in str(
                    details.query_one("#delivery-history-explanation", Static).render()
                )
                assert (
                    details.query_one("#delivery-historical-records", Static)
                    .render()
                    .plain
                    == ""
                )
                assert not any(
                    params.get("include_history") for _, params in owner_requests
                )
                app.save_screenshot(
                    filename="toad-delivery-history-inspector.svg", path="/var/tmp"
                )
                load = details.query_one(
                    "#delivery-load-history", DeliveryHistoryAction
                )
                # Hold the actual owner's history response while a newer receipt
                # reaches both the shared overview and the mounted inspector.
                original_read = agent.get_input_delivery
                captured, release = asyncio.Event(), asyncio.Event()
                history_reads = 0

                async def delayed_history(*, include_history=False):
                    nonlocal history_reads
                    result = await original_read(include_history=include_history)
                    if include_history:
                        history_reads += 1
                        if history_reads == 1:
                            captured.set()
                            await release.wait()
                    return result

                agent.get_input_delivery = delayed_history
                load.focus()
                loading = asyncio.create_task(pilot.press("enter"))
                try:
                    await asyncio.wait_for(captured.wait(), 3)
                    native_id = "a" * 32
                    assert store.bind(
                        "bus:933",
                        admission=admission,
                        turn_id="history-race",
                        native_id=native_id,
                        text="native prompt",
                    )
                    assert store.started(
                        "bus:933",
                        turn_id="history-race",
                        native_id=native_id,
                        text="native prompt",
                    )
                    await owner._emit_input_disposition(session, store.get("bus:933"))
                    await conversation.refresh_input_dispositions()
                    assert conversation.unresolved_inputs == []
                finally:
                    release.set()
                await loading
                await pilot.pause()
                agent.get_input_delivery = original_read
                assert history_reads >= 2
                assert conversation.unresolved_inputs == details.inputs == []
                assert any(
                    params.get("include_history") for _, params in owner_requests
                )
                historical = details.query_one("#delivery-historical-records", Static)
                assert "Historical notice 932:" in str(historical.render())
                assert len(details._historical_inputs) == 932
                assert conversation.input_delivery["historicalInputs"] == []
                assert records.region.y < historical.region.y

                store.record(
                    "bus:935",
                    seq=935,
                    owner=session,
                    admission=admission,
                    target="#review",
                    text="A new current input",
                )
                await owner._emit_input_disposition(session, store.get("bus:935"))
                await conversation.refresh_input_dispositions()

                # An older in-flight snapshot cannot resurrect a confirmed current input.
                original_read = agent.get_input_delivery
                captured, release = asyncio.Event(), asyncio.Event()
                reads = 0

                async def delayed_read(*, include_history=False):
                    nonlocal reads
                    reads += 1
                    result = await original_read(include_history=include_history)
                    if reads == 1:
                        captured.set()
                        await release.wait()
                    return result

                agent.get_input_delivery = delayed_read
                refresh = asyncio.create_task(conversation.refresh_input_dispositions())
                await captured.wait()
                native_id = "a" * 32
                assert store.bind(
                    "bus:935",
                    admission=admission,
                    turn_id="turn",
                    native_id=native_id,
                    text="native prompt",
                )
                assert store.started(
                    "bus:935", turn_id="turn", native_id=native_id, text="native prompt"
                )
                previous = conversation._delivery_refresh_revision
                await owner._emit_input_disposition(session, store.get("bus:935"))
                async with asyncio.timeout(3):
                    while conversation._delivery_refresh_revision == previous:
                        await asyncio.sleep(0.01)
                release.set()
                await refresh
                await pilot.pause()
                assert reads == 2
                agent.get_input_delivery = original_read
                assert conversation.unresolved_inputs == []
                assert bar.display and not bar.query_one("#delivery-summary").display
                assert bar.query_one("#delivery-history-summary").display
                assert "No current unconfirmed inputs." in str(records.render())
                assert "awaiting" not in str(
                    bar.query_one("#delivery-history-summary", Static).render()
                )

                # A failed dismissal remains visible and does not fabricate a cleared count.
                dismiss = agent.dismiss_historical_inputs

                async def failed_dismissal():
                    raise ValueError("Owner unavailable for this test")

                agent.dismiss_historical_inputs = failed_dismissal
                clear = details.query_one(
                    "#delivery-clear-history", DeliveryHistoryAction
                )
                clear.focus()
                await pilot.press("enter")
                await pilot.pause()
                assert "Owner unavailable" in str(
                    details.query_one("#delivery-error", Static).render()
                )
                assert (
                    details.query_one("#delivery-error")
                    in details._compositor.visible_widgets
                )
                assert conversation.input_delivery["historicalCount"] == 932
                assert bar.display
                store.record(
                    "bus:936",
                    seq=936,
                    owner=session,
                    admission=admission,
                    target="#review",
                    text="Current before clearing history",
                )
                await owner._emit_input_disposition(session, store.get("bus:936"))
                await conversation.refresh_input_dispositions()
                captured, release = asyncio.Event(), asyncio.Event()

                async def delayed_dismissal():
                    result = await dismiss()
                    captured.set()
                    await release.wait()
                    return result

                agent.dismiss_historical_inputs = delayed_dismissal
                clearing = asyncio.create_task(pilot.click("#delivery-clear-history"))
                try:
                    await asyncio.wait_for(captured.wait(), 3)
                    native_id = "b" * 32
                    assert store.bind(
                        "bus:936",
                        admission=admission,
                        turn_id="clear-race",
                        native_id=native_id,
                        text="native prompt",
                    )
                    assert store.started(
                        "bus:936",
                        turn_id="clear-race",
                        native_id=native_id,
                        text="native prompt",
                    )
                    store.record(
                        "bus:937",
                        seq=937,
                        owner=session,
                        admission=admission,
                        target="#review",
                        text="Current admitted during history clear",
                    )
                    await owner._emit_input_disposition(session, store.get("bus:936"))
                    await owner._emit_input_disposition(session, store.get("bus:937"))
                    await conversation.refresh_input_dispositions()
                    assert [
                        row["sequence"] for row in conversation.unresolved_inputs
                    ] == [937]
                finally:
                    release.set()
                await clearing
                await pilot.pause()
                agent.dismiss_historical_inputs = dismiss
                assert [row["sequence"] for row in conversation.unresolved_inputs] == [
                    937
                ]
                assert details.inputs == conversation.unresolved_inputs
                assert (
                    sum(
                        method == "dismiss_historical_inputs"
                        for method, _ in owner_requests
                    )
                    == 1
                )
                assert conversation.input_delivery["historicalCount"] == 0
                assert conversation.input_delivery["dismissedHistoricalCount"] == 932
                assert bar.display
                assert store.bind(
                    "bus:937",
                    admission=admission,
                    turn_id="after-clear",
                    native_id="c" * 32,
                    text="native prompt",
                )
                assert store.started(
                    "bus:937",
                    turn_id="after-clear",
                    native_id="c" * 32,
                    text="native prompt",
                )
                await owner._emit_input_disposition(session, store.get("bus:937"))
                await conversation.refresh_input_dispositions()
                await pilot.pause()
                assert not bar.display
                assert str(details.query_one("#delivery-error", Static).render()) == ""
                assert details._historical_inputs is None
                assert not clear.display
                assert details.query_one("#delivery-load-history").display
                detailed = await agent.get_input_delivery(include_history=True)
                assert len(detailed["historicalInputs"]) == 932
                assert all(
                    row["noticeDismissed"] for row in detailed["historicalInputs"]
                )
                saved = store._read()
                for key, original in old_rows.items():
                    assert all(
                        saved[key][field] == value for field, value in original.items()
                    )
                    assert not saved[key].get("goal_reviews")
                # Late notifications invalidate the view without restoring dismissed history.
                old = dict(store.get("bus:1"), status="unknown")
                await owner._emit_input_disposition(session, old)
                await pilot.pause()
                assert conversation.unresolved_inputs == []
                assert conversation.input_delivery["historicalCount"] == 0
                assert not bar.display
                assert store.status("bus:933") == "started"
                app.save_screenshot(
                    filename="toad-delivery-history-cleared.svg", path="/var/tmp"
                )
        finally:
            if proxy is not None:
                await proxy.close()
            await owner.shutdown()
    print(
        "delivery owner: current versus 932 legacy notices, explicit history load, visible failure, dismissal, and stale-update protection passed"
    )


if __name__ == "__main__":
    asyncio.run(main())
