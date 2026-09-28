"""Parent-run real-route UI observation. Never sends or starts an agent.

Normal mounted history may acknowledge painted messages. Run only as the
authorized integration owner, using the installed candidate Python and source
PYTHONPATH if not installed yet. No runtime_fixture (it stops test owners).
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import time

from agent_comms.comms import wire
from toad.app import ToadApp
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.message_notifications import MessageNotifications
from toad.widgets.observed_thread_activity import ObservedThreadActivity


async def until(predicate):
    async with asyncio.timeout(30):
        while not predicate():
            await asyncio.sleep(.05)


async def run(args):
    selected = wire()
    root = selected.root
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Isolate UI preferences only; retain the actual explicitly selected core route.
    os.environ.update(AGENT_COMMS_ROOT=str(root), XDG_CONFIG_HOME=str(output / "config"),
                      XDG_STATE_HOME=str(output / "state"), XDG_DATA_HOME=str(output / "data"))
    app = ToadApp(project_dir=args.project)
    report = {"root": str(root), "messages": [], "observations": [], "dm": None}
    async with app.run_test(size=(140, 52)) as pilot:
        await pilot.pause()
        owner = app.current_mode
        await app.open_comms_session(owner_mode=owner, project_path=Path(args.project),
                                     me="notification-ui-observer", target=args.channel, kind="channel")
        chat = app.screen.query_one(CommsChatView)
        await until(lambda: chat._history_initialized and not chat._refresh_lock.locked()
                    and not chat._edge_load_scheduled)
        await pilot.pause()
        for seq in args.seq:
            for _ in range(10):
                pair = next(((m, w) for m, w in chat._history if not m.view_key[0] and m.seq == seq), None)
                if pair is not None:
                    break
                if not chat._has_older:
                    raise AssertionError(f"Message {seq} not present in channel history")
                oldest = chat._history[0][0].view_order
                chat.window.release_anchor()
                chat.window.scroll_to(y=0, animate=False, immediate=True)
                chat._on_window_scroll()
                await until(lambda: not chat._edge_load_scheduled and chat._history[0][0].view_order < oldest)
            assert pair is not None, seq
            message, widget = pair
            widget.scroll_visible(animate=False, immediate=True, top=True)
            await pilot.pause()
            feedback = widget.query_one(MessageNotifications)
            chat._refresh_notifications()
            await until(lambda: "not checked" not in str(feedback.title))
            feedback.collapsed = False
            await pilot.pause()
            report["messages"].append({"seq": seq, "message_id": message.message_id,
                                       "summary": str(feedback.title),
                                       "details": str(feedback.details.render())})
            app.save_screenshot(filename=f"message-{seq}.svg", path=str(output))
            feedback.collapsed = True
        chat.window.scroll_end(animate=False, immediate=True)
        chat.window.anchor()
        started, previous = time.monotonic(), None
        while time.monotonic() - started < args.seconds:
            visible = set(chat._painted_message_keys())
            rows = [{"seq": m.seq, "message_id": m.message_id,
                     "summary": str(w.query_one(MessageNotifications).title),
                     "details": str(w.query_one(MessageNotifications).details.render())}
                    for m, w in chat._history if m.view_key in visible and w.query(MessageNotifications)]
            if rows != previous:
                event = {"elapsed": round(time.monotonic() - started, 3), "rows": rows}
                report["observations"].append(event)
                print(json.dumps(event), flush=True)
                previous = rows
            await asyncio.sleep(.05)
        if args.thread:
            await app.open_comms_session(owner_mode=owner, project_path=Path(args.project),
                                         me="notification-ui-observer", target=args.thread, kind="dm")
            dm = app.screen.query_one(CommsChatView)
            observed = dm.query_one(ObservedThreadActivity)
            await until(lambda: observed.presentation is not None or observed.unavailable)
            report["dm"] = {"thread": args.thread, "text": str(observed.render()),
                             "unavailable": observed.unavailable}
            app.save_screenshot(filename="dm-activity.svg", path=str(output))
        (output / "mounted.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({"messages": report["messages"], "dm": report["dm"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", default="/home/ts/.agent-comms")
    parser.add_argument("--channel", default="#comms")
    parser.add_argument("--seq", nargs="*", type=int, default=[63, 64])
    parser.add_argument("--thread", default="agent-comms-ux")
    parser.add_argument("--seconds", type=float, default=30)
    asyncio.run(run(parser.parse_args()))
