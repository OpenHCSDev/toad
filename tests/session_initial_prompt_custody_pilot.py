"""Mounted NoAgent prompt handoff and editor custody; no native/provider input."""

import asyncio
from collections import Counter
from importlib.resources import files
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from runtime_fixture import ToadApp
from toad.core.input_events import UserInputSubmitted
from toad.screens.main import MainScreen
from toad.widgets.conversation import ConversationSessionBinding


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


class ObservedLaunchScreen(MainScreen):
    """Observe the original stream; all creation and handlers stay native."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inputs = Counter()
        self.publication = asyncio.Event()
        self.subscriptions = []

    def observed(self, event, subscription):
        if isinstance(event, UserInputSubmitted):
            assert not event.shell
            self.inputs[event.body] += 1
            self.publication.set()

    def _make_conversation(self):
        conversation = super()._make_conversation()
        self.subscriptions.append(conversation.core_publications.subscribe(self.observed))
        return conversation


async def main(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    receipt = {"scope": "Mounted NoAgent constructor/eviction/remount/close and draft/Undo custody.",
               "native_inputs": 0, "provider_calls": 0, "public_inputs": 0}
    with TemporaryDirectory(prefix="initial-prompt-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        app = InstalledApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            await pilot.pause()

            # Original session-title acquisition refuses an unregistered source
            # before construction. No constructor or callback is replaced.
            candidate = MainScreen(root, initial_prompt="CONSTRUCTOR_PENDING")
            candidate.id = "not-an-admitted-session"
            try:
                candidate._make_conversation()
            except KeyError:
                assert candidate._initial_prompt == "CONSTRUCTOR_PENDING"
            else:
                raise AssertionError("Unregistered source unexpectedly constructed a conversation")
            candidate.id = app.selected_mode
            constructed = candidate._make_conversation()
            assert candidate._initial_prompt is None
            assert constructed.take_initial_prompt() == "CONSTRUCTOR_PENDING"
            assert constructed.take_initial_prompt() is None
            receipt["failed_constructor_retains_successful_constructor_transfers"] = True

            owner = ObservedLaunchScreen(root, initial_prompt="INITIAL_LOCAL_UI_EVENT")
            await app.session_navigation.new(lambda: owner)
            await owner.wait_content_ready()
            await asyncio.wait_for(owner.publication.wait(), 12)
            await pilot.pause()
            view = owner.conversation
            assert view.agent is None and not view.submissions.active
            assert owner._initial_prompt is None and view._initial_prompt is None
            assert owner.inputs == {"INITIAL_LOCAL_UI_EVENT": 1}

            editor = view.prompt.prompt_text_area
            editor.text = "DRAFT"
            editor.move_cursor((0, 5))
            editor.insert("Z")
            document, undo = editor.document, editor.history
            view.set_reactive(ConversationSessionBinding.agent_ready, False)
            view._initial_prompt = "NEWEST_PENDING_LOCAL_UI_EVENT"
            owner.publication.clear()
            await app.session_navigation.new(lambda: MainScreen(root))
            await app.selected_session.wait_content_ready()
            await owner.presentation.evict()
            assert view._initial_prompt is None
            assert owner.presentation.state.initial_prompt == "NEWEST_PENDING_LOCAL_UI_EVENT"
            assert owner.presentation.widget is None

            await app.select_session(owner.id)
            await asyncio.wait_for(owner.publication.wait(), 12)
            await pilot.pause()
            restored = owner.conversation
            assert restored is not view and restored.agent is None
            assert restored._initial_prompt is None and owner.presentation.state is None
            assert owner.inputs == {"INITIAL_LOCAL_UI_EVENT": 1, "NEWEST_PENDING_LOCAL_UI_EVENT": 1}
            editor = restored.prompt.prompt_text_area
            assert editor.document is document and editor.history is undo
            assert editor.text == "DRAFTZ"
            editor.focus()
            await pilot.press("ctrl+z")
            assert editor.text == "DRAFT"
            receipt["pending_eviction_remount_once_and_original_draft_undo"] = True

            # The consumed constructor value must stay absent on another eviction.
            await app.session_navigation.new(lambda: MainScreen(root))
            await app.selected_session.wait_content_ready()
            await owner.presentation.evict()
            assert owner.presentation.state.initial_prompt is None
            await app.select_session(owner.id)
            await pilot.pause()
            assert owner.inputs == {"INITIAL_LOCAL_UI_EVENT": 1, "NEWEST_PENDING_LOCAL_UI_EVENT": 1}
            assert owner.conversation.agent is None and not owner.conversation.submissions.active
            await app.session_navigation.close(owner.id)
            assert owner.presentation.widget is None and owner.presentation.state is None
            assert owner.id not in app.workspace_sessions.views
            assert app._exception is None
            receipt["consumed_input_not_restored_and_close_releases_state"] = True
            receipt["local_ui_publications"] = dict(owner.inputs)
        await asyncio.get_running_loop().shutdown_default_executor()
        assert app.preparation._closed and not app.preparation._pending
        assert app._exception is None
        receipt.update(state="PASS", cleanup=[])
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).resolve()))
