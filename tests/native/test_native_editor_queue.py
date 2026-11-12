"""Enter in the editor while a native turn runs queues the input; leaving and returning by tab click keeps the editor."""

from agent_comms.execution.pi_vocabulary import HighThinkingLevel
from agent_comms.projects.checkouts import Checkout
from support.native import native_session

from toad.acp.agent_configuration import AdvertisedSetting, ThinkingConfigurationSetting
from toad.navigation_context import NavigationContext
from toad.navigation_target import channel_target
from toad.widgets.model_switcher import SessionModelEditor
from toad.widgets.prompt import AgentInfo, QueueSummary
from toad.widgets.transcript_history import TranscriptHistory


async def test_enter_queues_during_a_turn_and_a_tab_click_returns_to_the_same_editor(workspace, native_package):
    async with native_session(workspace) as native:
        ui, agent, comms, provider = native.ui, native.agent, native.comms, native.provider
        app, pilot = ui.textual
        view = ui.conversation
        owner_tab = ui.selected_tab
        await ui.until_agent_ready()
        provider.hold_next_request()
        await ui.write_draft("NATIVE_EDITOR_FIRST")
        await ui.press("enter")
        await ui.until(
            provider.entered.is_set, seconds=30, why="the first input at the provider"
        )
        await ui.until(lambda: native.executing, seconds=20, why="the running turn")

        await ui.write_draft("NATIVE_EDITOR_QUEUED")
        await ui.press("enter")
        await ui.until(
            lambda: bool(view.submissions.queue_projection.items),
            seconds=20,
            why="the queued input",
        )
        assert "NATIVE_EDITOR_QUEUED" in view.query_one(QueueSummary).render().plain
        provider.release()
        await ui.until(
            lambda: len(provider.requests) == 2 and not native.executing,
            seconds=35,
            why="both turns to finish",
        )
        await ui.until(
            lambda: "NATIVE_RESPONSE_2" in ui.painted(view.window),
            seconds=25,
            why="the second answer",
        )
        await ui.until(
            lambda: not view.submissions.queue_projection.items
            and view.turns.managed_id is None,
            seconds=20,
            why="an empty queue and no turn",
        )
        assert ui.agent_ready()
        await ui.until(
            lambda: all(
                history.checkpoint_available
                for history in view.contents.query(TranscriptHistory)
            ),
            seconds=20,
            why="saved history to be available",
        )
        view.window.anchor()
        view.transcript.require_checkpoint()
        await ui.until(
            lambda: not view.transcript.dirty
            and "NATIVE_RESPONSE_2" in ui.painted(view.window),
            seconds=20,
            why="the answer from saved history",
        )
        assert view.contents.query(TranscriptHistory)
        assert view.transcript.displayed_cursor is not None

        await ui.write_draft("PRESERVED_UNSENT_DRAFT")
        editor = view.prompt.prompt_text_area
        document, undo = editor.document, editor.history
        owner = comms.registry.require("beta").process_identity
        assert await pilot.click(view.prompt.query_one(AgentInfo))
        popup = view.prompt.model_switcher
        await ui.until(
            lambda: popup.query_one(SessionModelEditor).search_input.has_focus,
            why="the model search in the configuration form",
        )
        previous_model = agent.configuration.model.current
        await ui.press("down", "enter")
        await ui.until(lambda: agent.configuration.model.current != previous_model,
                       why="the selected model")

        def thinking_editor():
            return next(row.editor for row in popup.form.values.values()
                        if isinstance(row.field.metadata(AdvertisedSetting).setting,
                                      ThinkingConfigurationSetting))

        await ui.until(
            lambda: thinking_editor().field.metadata(AdvertisedSetting).setting
                    == agent.configuration.thinking,
            why="the form to show the new model's thinking choices",
        )
        choices = tuple(choice.value for choice in agent.configuration.thinking.choices)
        assert "high" in choices
        thinking_editor().focus()
        await ui.press("enter", "home", *("down" for _ in range(choices.index("high"))), "enter")
        await ui.until(
            lambda: agent.configuration.thinking.current == "high",
            seconds=20,
            why="the thinking level",
        )
        assert comms.registry.require("beta").thinking_level is HighThinkingLevel

        user = comms.messaging.user_identity(Checkout(native.project)).name
        await channel_target("#team").open(
            NavigationContext(app, owner_tab, app.project_dir, user)
        )
        await app.selected_session.wait_content_ready()
        assert ui.selected_tab != owner_tab
        assert await pilot.click(f"SessionLabel#{owner_tab}")
        await ui.until(
            lambda: ui.selected_tab == owner_tab
            and "NATIVE_RESPONSE_2" in ui.painted(view.window),
            seconds=20,
            why="the session after clicking its tab",
        )
        assert ui.conversation is view
        assert ui.draft() == "PRESERVED_UNSENT_DRAFT"
        assert editor.document is document and editor.history is undo
        assert comms.registry.require("beta").process_identity == owner
        assert len(provider.requests) == 2
        await agent.session.reconnect()
        await ui.until(
            agent.session.settled.is_set, seconds=30, why="the reconnect to settle"
        )
        await ui.until(
            lambda: ui.agent_ready() and "NATIVE_RESPONSE_2" in ui.painted(view.window),
            seconds=20,
            why="history after reattaching",
        )
        assert agent.configuration.thinking.current == "high"
        assert (
            len(provider.requests) == 2 and not view.submissions.queue_projection.items
        )
