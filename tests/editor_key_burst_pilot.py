"""Observe original native key delivery during history-to-editor focus transfer."""

import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic_ns

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_comms.comms import Comms
from textual import events
from toad.app import ToadApp


async def main(output):
    output.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(dir=output) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        Comms(root / "wire").messaging.initialize_private_initial_protocol()
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            conversation = app.selected_session.conversation
            editor = conversation.prompt.prompt_text_area
            trace = []
            original_profile = sys.getprofile()

            def observe(frame, event, argument):
                if event != "call" or frame.f_code.co_name not in (
                        "on_key", "_on_key", "_forward_event", "action_cursor_left", "action_delete_left"):
                    return
                native_event = frame.f_locals.get("event")
                if native_event is not None and not isinstance(native_event, events.Key):
                    return
                trace.append({"at_ns": monotonic_ns(),
                              "consumer": frame.f_code.co_filename,
                              "method": frame.f_code.co_name,
                              "owner": type(frame.f_locals.get("self")).__name__,
                              "key": native_event.key if native_event is not None else None,
                              "focused_before": type(app.screen.focused).__name__,
                              "window_focused": conversation.window.has_focus,
                              "editor_text_before": editor.text,
                              "editor_selection_before": tuple(tuple(point) for point in editor.selection)})

            sys.setprofile(observe)
            try:
                async def burst(keys, *, editor_focused=False):
                    editor.clear()
                    target = editor if editor_focused else conversation.window
                    target.focus(scroll_visible=False)
                    await pilot.pause(.05)
                    assert app.screen.focused is target
                    began = monotonic_ns()
                    for key, character in keys:
                        event = events.Key(key, character)
                        event.set_sender(app)
                        app._driver.send_message(event)
                    await pilot.pause(.2)
                    return {"began_ns": began, "keys": [key for key, _ in keys],
                            "editor_focused_at_start": editor_focused,
                            "actual_text": editor.text,
                            "focused_after": type(app.screen.focused).__name__}

                deletion = await burst((("x", "x"), ("backspace", None)))
                arrows = await burst((("x", "x"), ("left", None), ("y", "y")))
                focused_arrows = await burst((("x", "x"), ("left", None), ("y", "y")),
                                             editor_focused=True)
                receipt = {"scope": "actual source Toad/native driver focus counter; not physical acceptance",
                           "deletion": deletion, "arrows": arrows,
                           "focused_arrows": focused_arrows, "trace": trace,
                           "agent_bound": conversation.agent is not None,
                           "exception": str(app._exception)}
                (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
                print(json.dumps(receipt), flush=True)
                assert conversation.agent is None and app._exception is None
                assert deletion["actual_text"] == "", "Printable insert succeeded but immediate deletion failed"
                assert arrows["actual_text"] == "yx", "Native arrow/printable burst lost editor key ordering"
            finally:
                sys.setprofile(original_profile)
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
