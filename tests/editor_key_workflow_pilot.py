"""Observe actual editor focus, key delivery and bindings without provider input."""
import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic
from traceback import extract_stack

from textual import events
from textual._context import active_message_pump, message_hook
from textual.widget import Widget
from toad.app import ToadApp
from toad.widgets.session_tabs import SessionLabel


class KeyWorkflowApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")

    def __init__(self, *args, evidence: Path, terminal=False, saved_history=False, **kwargs):
        self.evidence = evidence
        self.key_trace = []
        self.terminal = terminal
        self.saved_history = saved_history
        super().__init__(*args, **kwargs)

    def on_mount(self):
        if self.terminal:
            self.call_after_refresh(self.prepare_terminal)

    async def prepare_terminal(self):
        original_request = Widget.focus

        def observe_request(widget, scroll_visible=True):
            from toad.screens.session_view import SessionView
            source = next((ancestor for ancestor in widget.ancestors
                           if isinstance(ancestor, SessionView)), None)
            self.key_trace.append({"clock": monotonic(), "source": self.selected_mode,
                                   "focus_request": type(widget).__name__,
                                   "target_source": source.id if source is not None else None,
                                   "widget": id(widget), "focus": type(self.focused).__name__,
                                   "source_work": self.source_work(),
                                   "caller": [{"file": frame.filename, "line": frame.lineno,
                                               "function": frame.name}
                                              for frame in extract_stack(limit=12)[:-1]]})
            return original_request(widget, scroll_visible=scroll_visible)

        Widget.focus = observe_request
        original_focus = self.workspace_screen.set_focus

        def observe_focus(widget, scroll_visible=True):
            self.key_trace.append({"clock": monotonic(), "source": self.selected_mode,
                                   "focus_target": type(widget).__name__,
                                   "focus": type(self.focused).__name__,
                                   "source_work": self.source_work(),
                                   "caller": [{"file": frame.filename, "line": frame.lineno,
                                               "function": frame.name}
                                              for frame in extract_stack(limit=8)[:-1]]})
            return original_focus(widget, scroll_visible=scroll_visible)

        self.workspace_screen.set_focus = observe_focus
        first = self.selected_session
        if self.saved_history:
            await self.load_saved_history(first, 0)
        await self.session_navigation.create_from(self.selected_mode)
        if self.saved_history:
            await self.load_saved_history(self.selected_session, 1)
        self.set_interval(.05, self.record)
        self.record()
        (self.evidence / "ready").write_text("Two actual local editor tabs; no agent/provider input\n")

    async def load_saved_history(self, source, index):
        from agent_comms.comms import wire
        from agent_comms.threads import Thread
        from toad.widgets.transcript_history import TranscriptHistory

        root = Path(os.environ["AGENT_COMMS_ROOT"])
        session = root.parent / f"editor-source-{index}.jsonl"
        session.write_text("\n".join(json.dumps({"type": "message", "message": {
            "role": "assistant", "content": f"## Saved source {index}, record {number}\n\n"
            + "Actual lazy document **body** and editor focus.\n\n" * 12}})
            for number in range(105)) + "\n")
        comms = wire(root)
        name = f"editor-source-{index}"
        comms.registry.declare(Thread(name, frozenset(), str(root.parent), session_file=str(session)))

        async def read(**kwargs):
            return await asyncio.to_thread(comms.transcripts.thread_transcript_page, name, **kwargs)

        page = await read()
        await source.conversation.post(TranscriptHistory(page, loader=read))

    def source_work(self):
        source = self.selected_session
        if source is None:
            return []
        return [type(history.state).__name__ for history in source.conversation.window.histories]

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if (self.terminal and self.saved_history and self.selected_session is not None
                and self.selected_session.conversation.query("PromptTextArea")):
            self.record()

    def observe_key(self, message):
        if isinstance(message, events.Key):
            self.key_trace.append({
                "clock": monotonic(), "source": self.selected_mode,
                "key": message.key, "character": message.character,
                "receiver": type(active_message_pump.get()).__name__,
                "focus": type(self.focused).__name__,
                "stopped": message._stop_propagation,
                "source_work": self.source_work(),
            })

    async def run_action(self, action, default_namespace=None):
        result = await super().run_action(action, default_namespace)
        self.key_trace.append({"action": action, "namespace": type(default_namespace).__name__,
                               "accepted": result, "focus": type(self.focused).__name__,
                               "clock": monotonic(), "source": self.selected_mode,
                               "source_work": self.source_work()})
        self.record()
        return result

    def record(self):
        source = self.selected_session
        if source is None:
            return
        area = source.conversation.prompt.prompt_text_area
        self.evidence.mkdir(parents=True, exist_ok=True)
        current = self.evidence / "current-ui.json"
        temporary = current.with_suffix(".new")
        temporary.write_text(json.dumps({
            "source": self.selected_mode, "driver": type(self._driver).__name__,
            "toad_package": str(files("toad")),
            "focused": type(self.focused).__name__, "editor_focused": area.has_focus,
            "editor_owns_keys": self.focused is area,
            "loading": area.loading, "disabled": area.is_disabled,
            "read_only": area.read_only, "usable_cursor": area._has_cursor,
            "clock": monotonic(), "source_work": self.source_work(),
            "text": area.text, "cursor": area.cursor_location,
            "document": id(area.document), "history": id(area.history),
            "editor_region": list(area.region),
            "window_region": list(source.conversation.window.region),
            "tabs": [{"source": tab.id, "region": list(tab.region)}
                     for tab in self.screen.query(SessionLabel)],
            "bindings": [{"namespace": type(owner).__name__,
                          "keys": sorted(bindings.key_to_bindings)}
                         for owner, bindings in self.screen._binding_chain],
        }, indent=2) + "\n")
        temporary.replace(current)
        (self.evidence / "key-trace.json").write_text(json.dumps(self.key_trace, indent=2) + "\n")


async def edit_keys(pilot, area):
    """Typing and deletion exercise the same native editor document and undo."""
    initial, cursor = area.text, area.cursor_location
    assert area.has_focus
    area.history.checkpoint()
    await pilot.press(*"abcd", "left")
    assert area.cursor_location == (cursor[0], cursor[1] + 3)
    await pilot.press("backspace", "delete")
    assert area.text == initial[:cursor[1]] + "ab" + initial[cursor[1]:]
    await pilot.press("left", "right")
    assert area.cursor_location == (cursor[0], cursor[1] + 2)
    await pilot.press("backspace", "backspace")
    assert area.text == initial and area.cursor_location == cursor
    area.history.checkpoint()
    await pilot.press("ctrl+z")
    await pilot.pause()
    assert area.text != initial
    await pilot.press("backspace", "backspace")
    await pilot.pause()
    assert area.text == initial


async def main():
    evidence = Path(os.environ["EDITOR_KEY_EVIDENCE"])
    with TemporaryDirectory(prefix="editor-keys-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_DATA_HOME=str(root / "data"), XDG_STATE_HOME=str(root / "state"))
        app = KeyWorkflowApp(project_dir=str(root), evidence=evidence)
        async with app.run_test(size=(120, 40), message_hook=app.observe_key) as pilot:
            await pilot.pause()
            first = app.selected_session
            first_area = first.conversation.prompt.prompt_text_area
            assert await pilot.click(first_area)
            await edit_keys(pilot, first_area)
            await pilot.press("escape", "tab", "shift+tab")
            assert await pilot.click(first_area)
            await edit_keys(pilot, first_area)
            await app.session_navigation.create_from(first.id)
            await pilot.pause()
            second = app.selected_session
            for source in (first, second, first):
                tab = app.screen.query_one(f"SessionLabel#{source.id}", SessionLabel)
                assert await pilot.click(tab)
                await pilot.pause()
                area = source.conversation.prompt.prompt_text_area
                assert app.selected_session is source
                assert area.has_focus, type(app.focused).__name__
                await edit_keys(pilot, area)
            assert first_area.document is first.conversation.prompt.prompt_text_area.document
            app.record()
            assert app._exception is None
        print("ACTUAL_EDITOR_CLICK_TRAVERSAL_ABA_PRINTABLE_LEFT_RIGHT_BACKSPACE_DELETE_UNDO_PASS")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] in {"--terminal", "--terminal-history"}:
        app = KeyWorkflowApp(project_dir=sys.argv[2], evidence=Path(sys.argv[3]), terminal=True,
                             saved_history=sys.argv[1] == "--terminal-history")
        token = message_hook.set(app.observe_key)
        try:
            app.run()
        finally:
            message_hook.reset(token)
    else:
        asyncio.run(main())
