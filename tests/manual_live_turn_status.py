"""Explicit opt-in check of installed Toad/ACP against the active comms route.

Run from the candidate environment. This uses actual live threads and never
creates or destroys owners; set LIVE_STATUS_SEND=1 to send one test prompt.
"""
import asyncio
import os
import sys
from pathlib import Path

from toad.app import ToadApp
from toad.widgets.conversation import TurnActivity
from toad.widgets.prompt import Prompt
from toad.widgets.throbber import Throbber
from toad.widgets.session_tabs import SessionLabel
from toad.widgets.session_details import SessionDetails
from toad.widgets.goal_bar import GoalBar
from saved_state_user_journey_pilot import click_thread


def acp_agent():
    return {
        "identity": "agent-comms-live-check.custom.batrachian.ai",
        "name": "Agent Comms",
        "short_name": "agent",
        "url": "https://github.com/batrachianai/toad",
        "protocol": "acp",
        "type": "coding",
        "author_name": "Will McGugan",
        "author_url": "https://willmcgugan.github.io/",
        "publisher_name": "Will McGugan",
        "publisher_url": "https://willmcgugan.github.io/",
        "description": "Live installed UI check",
        "tags": [],
        "help": "",
        "run_command": {"*": f"{sys.executable} -m agent_comms.acp"},
        "actions": {},
    }


async def ready(pilot, app, source):
    for _ in range(400):
        await pilot.pause(.1)
        if app._exception is not None:
            raise app._exception
        view = source.conversation
        if (view.agent is not None and view.agent.ready
                and view.query_one_optional(Prompt) is not None):
            return view
    raise TimeoutError(f"Live {source.id} did not attach")


def state(source):
    view = source.conversation
    row = view.query_one(TurnActivity)
    return (view.agent.session_id, view.agent.current_turn.busy,
            view.turns.owner.busy, row.owner.activity, row.visible,
            view.query_one(Throbber).busy, view.prompt.agent_busy,
            view.prompt.prompt_text_area.agent_busy,
            str(view.query_one(SessionDetails).title))


def require_current_activity(source):
    view = source.conversation
    busy = view.agent.current_turn.busy
    row = view.query_one(TurnActivity)
    assert view.turns.owner.busy == busy
    assert row.visible == bool(view.agent.current_turn.activity)
    assert view.query_one(Throbber).busy == (busy or view.busy_count > 0)
    assert view.prompt.agent_busy == busy
    assert view.prompt.prompt_text_area.agent_busy == busy
    if not busy:
        assert "Thinking" not in str(view.query_one(SessionDetails).title)


async def select_tab(pilot, app, source):
    tab = next(label for label in app.screen.query(SessionLabel) if label.id == source.id)
    tab.scroll_visible(animate=False, immediate=True)
    await pilot.pause(.1)
    assert await pilot.click(tab)
    for _ in range(100):
        await pilot.pause(.1)
        if app.selected_mode == source.id:
            return
    raise TimeoutError(
        f"Tab {source.id} was not selected; selected={app.selected_mode}; "
        f"switch_lock={app._mode_switch_lock.locked()}; "
        f"pending={app._pending_mode_switch}; atomic={app._atomic_mode_switch}; "
        f"error={app._exception!r}"
    )


async def main():
    from agent_comms.comms import wire
    comms = wire()
    agent = acp_agent()
    owner = os.environ.get("LIVE_STATUS_OWNER", "agent-comms-ux")
    peer = os.environ.get("LIVE_STATUS_PEER", "nra-architecture")
    project = Path(comms.registry.require(owner).worktree)
    app = ToadApp(agent_data=agent, project_dir=str(project),
                  agent_session_id=owner)
    async with app.run_test(headless=True, size=(140, 36)) as pilot:
        first = app.selected_session
        first_view = await ready(pilot, app, first)
        print("LIVE_FIRST", state(first), flush=True)
        peer_tags = comms.registry.require(peer).tags
        peer_channel = "#" + next(iter(sorted(peer_tags))) if peer_tags else "#any"
        second = await click_thread(app, pilot, peer, peer_channel)
        await ready(pilot, app, second)
        print("LIVE_SECOND", state(second), flush=True)
        if os.environ.get("LIVE_STATUS_SEND") == "1":
            await select_tab(pilot, app, first)
            prompt = os.environ.get("LIVE_STATUS_PROMPT", "Reply exactly LIVE_STATUS_CHECK. This is a Toad UI activity check; do not change goals or files.")
            if os.environ.get("LIVE_STATUS_DIRECT") == "1":
                submitted = asyncio.create_task(first_view.agent.send_prompt(prompt))
            else:
                editor = first_view.prompt.prompt_text_area
                assert await pilot.click(editor)
                editor.insert(prompt)
                await pilot.press("enter")
                print("LIVE_AFTER_SEND", repr(editor.text), editor.agent_ready,
                      first_view.submissions.queue_projection.status, repr(first_view.submissions.delivering),
                      flush=True)
            for _ in range(100):
                await pilot.pause(.1)
                if first_view.agent.current_turn.busy:
                    break
            else:
                raise TimeoutError("Live native turn did not start")
            print("LIVE_ACTIVE", state(first), flush=True)
            require_current_activity(first)
            await select_tab(pilot, app, second)
            print("LIVE_OTHER_DURING_TURN", state(second), flush=True)
            require_current_activity(second)
            await select_tab(pilot, app, first)
            for _ in range(3000):
                await pilot.pause(.1)
                if not first_view.agent.current_turn.busy:
                    break
            else:
                raise TimeoutError("Live native turn did not settle")
            print("LIVE_AFTER_TURN", state(first), flush=True)
            require_current_activity(first)
            if os.environ.get("LIVE_STATUS_DIRECT") == "1":
                await asyncio.wait_for(submitted, 30)
        await select_tab(pilot, app, second)
        await pilot.pause(.3)
        print("LIVE_SECOND_RETURN", state(second), flush=True)
        require_current_activity(second)
        await select_tab(pilot, app, first)
        await pilot.pause(.3)
        print("LIVE_FIRST_RETURN", state(first), flush=True)
        require_current_activity(first)
        for source in (first, second):
            await select_tab(pilot, app, source)
            await ready(pilot, app, source)
            view = source.conversation
            await view.goal_observation.refresh()
            bar = view.query_one(GoalBar)
            expected = comms.registry.require(view.agent.session_id).goal
            assert view.goal_display.snapshot == expected
            assert bar.goal_display is view.goal_display
            assert bar.display == view.goal_display.visible
            print("LIVE_GOAL_CURRENT_OWNER", view.agent.session_id,
                  "absent" if expected is None else expected.text[:50], flush=True)


if __name__ == "__main__":
    asyncio.run(main())
