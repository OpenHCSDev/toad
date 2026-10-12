"""Launching a catalog agent from the Store starts a second native session without sending anything,
and the session that was open keeps its owner, draft and editor."""


from support.catalog import IDENTITY, private_catalog_entry
from support.catalog_steps import choose_action, open_agent
from support.native import native_session
from toad.screens.agent_modal import AgentModal
from toad.screens.store import AgentItem, LauncherGridSelect, LauncherItem, StoreScreen


async def test_store_launch_starts_a_session_and_leaves_the_open_one_alone(workspace, native_package):
    with private_catalog_entry() as definition:
        from toad.app import ToadApp

        def with_catalog_agent(**arguments):
            return ToadApp(**{**arguments, "agent_data": definition})

        async with native_session(workspace, native_package, application=with_catalog_agent) as native:
            ui, agent, comms, provider = native.ui, native.agent, native.comms, native.provider
            app, _pilot = ui.textual
            view = ui.conversation
            first_tab = ui.selected_tab
            await ui.until_agent_ready()
            await ui.write_draft("NEW_CATALOG_CONTROL")
            await ui.press("enter")
            await ui.until(lambda: "NATIVE_RESPONSE_1" in ui.painted(view.window), seconds=30, why="the answer")
            await ui.until(lambda: not native.executing, seconds=20, why="the turn to finish")
            owner = comms.registry.require("beta").process_identity
            await ui.write_draft("KEEP_CATALOG_DRAFT")
            document = view.prompt.prompt_text_area.document
            undo = view.prompt.prompt_text_area.history

            async def open_store():
                view.window.focus()
                await ui.press("ctrl+h")
                await ui.until(lambda: isinstance(app.screen, StoreScreen), why="the Store")
                return app.screen

            store = await open_store()
            await ui.until(lambda: any(item.agent.identity == IDENTITY for item in store.query(AgentItem)),
                           why="the catalog entry")
            await open_agent(ui, next(item for item in store.query(AgentItem) if item.agent.identity == IDENTITY))
            modal = app.screen
            assert ui.shows("requires an ACP adapter")
            assert modal.agent is store.agents[IDENTITY]
            app.settings.launcher.agents = IDENTITY  # as a successful install records it
            await choose_action(ui, modal, None)
            await ui.until(lambda: ui.selected_tab not in {first_tab, "store"}, seconds=20, why="the launched session's tab")
            launched = ui.conversation
            await ui.until(lambda: launched.agent_ready, seconds=40, why="the launched agent to be ready")
            assert launched.agent.definition.identity == IDENTITY
            assert len(provider.requests) == 1, "Launching from the Store asked the model"

            await ui.select_tab(first_tab)
            assert ui.conversation is view
            assert ui.draft() == "KEEP_CATALOG_DRAFT"
            assert view.prompt.prompt_text_area.document is document
            assert view.prompt.prompt_text_area.history is undo
            assert comms.registry.require("beta").process_identity == owner

            store = await open_store()
            await ui.until(lambda: any(item.agent.identity == IDENTITY for item in store.query(LauncherItem)),
                           why="the launcher entry")
            await open_agent(ui, next(item for item in store.query(LauncherItem) if item.agent.identity == IDENTITY))
            await ui.press("escape")
            await ui.until(lambda: isinstance(app.screen, StoreScreen), why="the Store again")
            grid = store.query_one(LauncherGridSelect)
            grid.focus()
            await grid.run_action("details")
            await ui.until(lambda: isinstance(app.screen, AgentModal), why="the agent dialog from the launcher")
            assert app.screen.agent is store.agents[IDENTITY]
            await ui.press("escape")
            await ui.until(lambda: isinstance(app.screen, StoreScreen), why="the Store again")
            assert len(provider.requests) == 1
            await launched.agent.stop()
