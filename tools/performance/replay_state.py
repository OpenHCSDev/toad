"""Offline headless replay of trusted captured DTOs with a private wire/store.

This reconstructs loaded text/page data and view controls, not a process image.
The v3 bundle lacks transient live tool widgets and some live input metadata.
No providers are launched and no original wire roots are used for operations.
"""

import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import pickle
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from agent_comms import Thread, TranscriptPage, wire
from toad.app import ToadApp
from toad.acp.messages import CoordinationUpdate
from toad.screens.main import MainScreen
from toad.session_tracker import SidebarSelection, SidebarState
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.message_filter import ALL_CATEGORIES, MESSAGE_CATEGORIES, MessageCategory
from toad.widgets.side_bar import SideBar
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.user_input import UserInput


def make_block(record):
    kind, text = record["kind"], record["text"]
    if kind == "AgentThought":
        return AgentThought(text)
    if kind == "UserInput":
        return UserInput(text)
    category = MessageCategory.INBOUND if kind == "IncomingMessage" else None
    return AgentResponse(text, route=record.get("route"), category=category)


def ownership(app):
    closed = Counter()
    live = 0
    for node in app._registry:
        for attribute, watchers in vars(node).get("__watchers", {}).items():
            for subscriber, _ in watchers:
                if subscriber._closed:
                    closed[type(node).__name__, attribute, type(subscriber).__name__] += 1
                else:
                    live += 1
    return {"registered_widgets": len(app._registry), "live_watch_subscriptions": live,
            "closed_watch_subscriptions": sum(closed.values()),
            "closed_watch_paths": [(list(path), count) for path, count in closed.most_common()]}


async def main(args):
    with args.bundle.open("rb") as source:
        saved = pickle.load(source)
    assert saved["schema"] == 1
    if args.legacy_watches:
        from textual.reactive import Reactive
        Reactive._clear_watch_subscriptions = classmethod(lambda cls, node: None)
    report = {"bundle": str(args.bundle), "legacy_watches": args.legacy_watches,
              "scope": "captured loaded pages/direct text blocks; no live agents or original wire access",
              "views": [], "actions": [], "completed": False}
    start = time.monotonic()
    with TemporaryDirectory(prefix="toad-captured-replay-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        for key in ("AGENT_COMMS_THREAD", "AGENT_COMMS_MANAGED", "PI_AGENT_ID", "PI_PARENT_ID", "PI_TASK", "PI_WORKTREE", "PI_PROMPT"):
            os.environ.pop(key, None)
        comms = wire(root / "wire")
        snapshot = saved["sidebar_snapshot"]
        for person in snapshot.threads:
            # Recreate names/tags, not live executor ownership or active turns.
            comms.register(Thread(person.thread.name, person.thread.tags, str(root), pid=os.getpid()))
        for channel in snapshot.channels:
            if channel.channel.builtin is None:
                comms.set_channel(channel.channel.name, channel.channel.tags)
        registered = {person.thread.name for person in snapshot.threads}
        for view in saved["views"]:
            for message in view.get("wire_history", ()):
                for target in (message.sender, message.target):
                    if not target.startswith("#") and target not in registered:
                        comms.register(Thread(target, frozenset(), str(root), pid=os.getpid()))
                        registered.add(target)
        seen_messages = set()
        for view in saved["views"]:
            for message in view.get("wire_history", ()):
                identity = (message.sender, message.target, message.seq, message.body)
                if identity not in seen_messages:
                    seen_messages.add(identity)
                    comms.send(message.sender, message.target, message.body)
        app = ToadApp(project_dir=str(root))
        app._sidebar_snapshot = snapshot
        if state := saved.get("sidebar_state"):
            state = dict(state)
            if state.get("selected") is not None:
                state["selected"] = SidebarSelection(**state["selected"])
            app.sidebar_state = SidebarState(**state)
        if saved.get("sidebar_layout"):
            app.sidebar_layout.placements = dict(saved["sidebar_layout"])
        modes = {}
        try:
            with patch.object(CommsSidebar, "_refresh", lambda self: None):
                async with app.run_test(size=tuple(saved["metadata"].get("size") or (140, 45))) as pilot:
                    await pilot.pause()
                    native_views = [view for view in saved["views"] if view["screen_class"] == "MainScreen"]
                    for index, captured in enumerate(native_views):
                        if index:
                            await app.new_session_screen(lambda: MainScreen(root))
                        await pilot.pause()
                        mode = modes[captured["mode"]] = app.current_mode
                        screen = app.screen
                        identity = captured["identity"]
                        await screen.on_coordination_update(CoordinationUpdate(
                            thread=identity["_comms_thread"], wire_root=str(comms.root),
                            persistence="offline-replay", transport="offline-replay"))
                        view = screen.conversation
                        restored_pages = 0
                        for history in captured["history_pages"]:
                            through = history.get("through")
                            if through is None or not through.session_file:
                                continue  # Synthetic nested pagers are recreated from their outer text.
                            pages = [page for page, _, _ in history["pages"]]
                            if pages:
                                bounded = TranscriptPage(tuple(event for page in pages for event in page.events),
                                                         pages[0].before, pages[-1].after, False, False)
                                await view.contents.mount(TranscriptHistory(bounded))
                                restored_pages += len(pages)
                        blocks = [record for record in captured["live_blocks"] if record["parent_class"] == "Contents"]
                        for offset in range(0, len(blocks), 16):
                            await view.contents.mount(*(make_block(record) for record in blocks[offset:offset+16]))
                        view.visible_categories = frozenset(MessageCategory(value) for value in captured.get("visible_categories", ALL_CATEGORIES))
                        view.goal = captured.get("goal")
                        view.goal_execution = captured.get("goal_execution")
                        if captured["drafts"] and captured["drafts"][0]["lines"] is not None:
                            view.prompt.text = "\n".join(captured["drafts"][0]["lines"])
                        for bar in captured["bars"]:
                            screen.query_one(f"#{bar['id']}", SideBar).collapsed = bool(bar["collapsed"])
                        await pilot.pause()
                        if captured["history_windows"]:
                            position = captured["history_windows"][0]
                            if position.get("_is_anchored") and not position.get("_anchor_released"):
                                view.window.anchor()
                            else:
                                view.window.release_anchor()
                                view.window.scroll_to(y=position.get("_reactive_scroll_y") or 0, animate=False, immediate=True)
                        report["views"].append({"saved_mode": captured["mode"], "mode": mode,
                                                "loaded_pages": restored_pages, "direct_text_blocks": len(blocks)})
                        print("Restored", captured["mode"], "pages", restored_pages, "text blocks", len(blocks), flush=True)
                    for captured in saved["views"]:
                        if captured["screen_class"] != "CommsScreen":
                            continue
                        identity = captured["identity"]
                        mode = await app.open_comms_session(owner_mode=modes[identity["owner_mode"]], project_path=root,
                            me=identity["me"], target=identity["target"], kind=identity["kind"])
                        modes[captured["mode"]] = mode
                        await pilot.pause()
                        report["views"].append({"saved_mode": captured["mode"], "mode": mode,
                                                "captured_wire_messages": len(captured.get("wire_history", ()))})
                    app._open_tab_order[:] = [modes[mode] for mode in saved["metadata"]["open_tab_order"] if mode in modes]
                    app.open_tabs_changed.publish(None)
                    await app.switch_mode(modes[saved["metadata"]["current_mode"]])
                    await pilot.pause()
                    report["setup_seconds"] = round(time.monotonic()-start, 2)
                    report["before"] = ownership(app)
                    report["mode_mapping"] = modes
                    for captured in native_views[:args.exercise_views]:
                        mode = modes[captured["mode"]]
                        begun = time.monotonic()
                        await app.switch_mode(mode)
                        await pilot.pause()
                        report["actions"].append({"kind": "switch", "mode": mode,
                                                  "settled_ms": (time.monotonic()-begun)*1000})
                        view = app.screen.conversation
                        original = view.visible_categories
                        draft = view.prompt.text
                        for category in MESSAGE_CATEGORIES:
                            begun = time.monotonic()
                            setter_start, setter_cpu = time.monotonic_ns(), time.thread_time_ns()
                            view.visible_categories = view.visible_categories ^ {category}
                            setter_ms = (time.monotonic_ns()-setter_start)/1e6
                            setter_cpu_ms = (time.thread_time_ns()-setter_cpu)/1e6
                            view.prompt.focus()
                            await pilot.press("x")
                            draft += "x"
                            assert view.prompt.text == draft
                            await pilot.pause()
                            restore_start = time.monotonic_ns()
                            view.visible_categories = original
                            restore_ms = (time.monotonic_ns()-restore_start)/1e6
                            await pilot.pause()
                            report["actions"].append({"kind": "filter", "mode": mode, "category": category.value,
                                                      "setter_ms": setter_ms, "setter_cpu_ms": setter_cpu_ms,
                                                      "restore_setter_ms": restore_ms,
                                                      "settled_ms": (time.monotonic()-begun)*1000})
                    report["after"] = ownership(app)
                    assert app._exception is None
                    report["completed"] = True
        finally:
            report["total_seconds"] = round(time.monotonic()-start, 2)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exercise-views", type=int, default=3)
    parser.add_argument("--legacy-watches", action="store_true")
    asyncio.run(main(parser.parse_args()))
