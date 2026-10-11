"""Textual-facing: a welcome note still being published when the conversation's source changes does not consume or clear the next source's pending input."""

import asyncio

from toad.agent_schema import AgentDefinition
from toad.screens.main import MainScreen
from toad.widgets.markdown_note import MarkdownNote


async def test_a_retired_welcome_publication_leaves_the_next_sources_input_alone(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        app, _ = ui.textual
        view = ui.conversation
        old_source = view.transcript
        entered, release = asyncio.Event(), asyncio.Event()
        original_post = view.post

        async def delayed_post(note):
            # Publish for real, delaying only completion to expose the ordinary
            # asynchronous source-change boundary.
            result = await original_post(note)
            entered.set()
            await release.wait()
            return result

        view._agent_data = AgentDefinition.decode({
            "name": "Welcome probe", "identity": "welcome-source-probe", "short_name": "probe",
            "protocol": "acp", "run_command": {"*": "true"}, "welcome": "OLD_SOURCE_WELCOME"})
        view._native_agent_started_here = True
        view.post = delayed_post
        worker = view.watch_agent_ready(True)
        try:
            async with asyncio.timeout(12):
                await entered.wait()
                assert view.query(MarkdownNote)
                await app.session_navigation.new(lambda: MainScreen(workspace.project))
                await app.selected_session.wait_content_ready()
                await ui.step()
                assert ui.conversation is view
                assert view.transcript is not old_source
                # This pending input is deliberately not submitted by the test.
                # A retired callback must neither clear nor post it.
                view._initial_prompt = "NEXT_SOURCE_OWNED_INPUT"
                release.set()
                await worker.wait()
                await ui.step()
                assert view._initial_prompt == "NEXT_SOURCE_OWNED_INPUT"
        finally:
            release.set()
            view.post = original_post
            view._initial_prompt = None

