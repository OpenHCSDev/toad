"""Textual-facing: the title in a new ACP session's first metadata names the tab (a Textual tab label) and the saved session without switching tabs."""

from contextlib import nullcontext
from unittest.mock import AsyncMock, patch

import pytest
from acp.schema import AgentCapabilities, InitializeResponse, LoadSessionResponse, NewSessionResponse
from agent_comms.acp_extension import encode_updates

from support.agents import command
from support.coordination import coordination_fact
from toad.acp.agent import Agent
from toad.core.events import SessionInfoUpdate
from toad.db import DB

THREAD = "existing-worker"


class Response:
    def __init__(self, payload):
        self.payload = payload

    async def wait(self):
        return self.payload


def resumable_agent(workspace, session_id=None, session_pk=None):
    """An agent object with no process whose handshake advertises session loading."""
    agent = Agent(workspace.project, command("false", name="fixture", identity="agent-comms.openhcs.dev"),
                  session_id, session_pk)
    agent.process.initialization = InitializeResponse(
        protocolVersion=1, agentCapabilities=AgentCapabilities(loadSession=True))
    return agent


def metadata(workspace, title):
    return encode_updates(coordination_fact(THREAD, workspace.roots.wire, title=title, worktree=workspace.project))


def tab_title(ui, identity):
    return next(tab.title for tab in ui.tabs() if tab.identity == identity)


@pytest.mark.parametrize("title", ["An already named thread", None], ids=["named", "unnamed"])
async def test_new_session_metadata_names_the_tab_and_the_saved_session(workspace, title):
    expected = title or THREAD
    workspace.thread(THREAD, "acp", title=title)
    meta = metadata(workspace, title)
    created, loaded_response = NewSessionResponse(sessionId=THREAD, _meta=meta), LoadSessionResponse(_meta=meta)
    created_titles = []
    create_session = DB.session_new

    async def record_creation(db, name, *args, **kwargs):
        created_titles.append(name)
        return await create_session(db, name, *args, **kwargs)

    async with workspace.app(size=(120, 40)) as ui:
        app, _pilot = ui.textual
        mode = ui.selected_tab
        agent = resumable_agent(workspace)
        ui.attach_agent(agent)
        with (
            patch.object(agent, "request", return_value=nullcontext()),
            patch("toad.acp.agent_session.api.session_new", return_value=Response(created)),
            patch.object(DB, "session_new", new=record_creation),
        ):
            await agent.session.new()
        await ui.until(lambda: expected in tab_title(ui, mode), why="the tab to carry the thread's title")
        assert created_titles == [expected], ("saved title at creation", created_titles, expected)
        assert ui.selected_tab == mode, "No tab switch should be needed"
        assert app.session_tracker.get_session(mode).title == expected
        assert agent.session.pk is not None
        assert (await DB().session_get(agent.session.pk)).title == expected
        assert workspace.comms.registry.require(THREAD).title == title, "Presenting a title must not rename the thread"


@pytest.mark.parametrize("title", ["An already named thread", None], ids=["named", "unnamed"])
async def test_loading_a_saved_session_names_its_tab_and_keeps_an_explicit_label(workspace, title):
    expected = title or THREAD
    workspace.thread(THREAD, "acp", title=title)
    meta = metadata(workspace, title)
    created, loaded_response = NewSessionResponse(sessionId=THREAD, _meta=meta), LoadSessionResponse(_meta=meta)
    async with workspace.app(size=(120, 40)) as ui:
        app, _pilot = ui.textual
        agent = resumable_agent(workspace)
        ui.attach_agent(agent)
        with (
            patch.object(agent, "request", return_value=nullcontext()),
            patch("toad.acp.agent_session.api.session_new", return_value=Response(created)),
        ):
            await agent.session.new()
        loaded = await ui.new_session()
        resumed = resumable_agent(workspace, THREAD, agent.session.pk)
        ui.attach_agent(resumed)
        with (
            patch.object(resumed, "request", return_value=nullcontext()),
            patch("toad.acp.agent_session.api.session_load", return_value=Response(loaded_response)),
        ):
            await resumed.session.load()
        await ui.until(lambda: expected in tab_title(ui, loaded), why="the loaded tab to carry the thread's title")
        assert ui.selected_tab == loaded
        assert app.session_tracker.get_session(loaded).title == expected
        assert (await DB().session_get(agent.session.pk)).title == expected
        app.session_tracker.update_session(loaded, title="My explicit label")
        app.selected_session.on_comms_session_named(THREAD)
        assert app.session_tracker.get_session(loaded).title == "My explicit label"
        resumed.comms_consumer_class(resumed, resumed.session_id).dispatch_sync(
            coordination_fact(THREAD, workspace.roots.wire))
        await ui.step()
        assert app.session_tracker.get_session(loaded).title == "My explicit label"


async def new_session_with_pending_name(workspace):
    created = NewSessionResponse(sessionId=THREAD, _meta=metadata(workspace, None))
    agent = resumable_agent(workspace)
    agent.session.chosen_name = "My pending title"
    saved = AsyncMock(return_value=7)
    updates = []
    with (
        patch.object(agent, "request", return_value=nullcontext()),
        patch("toad.acp.agent_session.api.session_new", return_value=Response(created)),
        patch.object(DB, "session_new", new=saved),
        patch.object(DB, "session_update_title", new=AsyncMock()),
        patch.object(agent.session, "rename_coordination"),
        agent.events.subscribe(lambda event, _subscription: updates.append(event)),
    ):
        await agent.session.new()
    return saved, updates


async def test_a_name_chosen_before_the_session_exists_is_saved_with_the_session(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        saved, _updates = await new_session_with_pending_name(workspace)
        assert saved.call_args.args[0] == "My pending title"


async def test_a_name_chosen_before_the_session_exists_is_announced_as_its_title(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        _saved, updates = await new_session_with_pending_name(workspace)
        assert [event.title for event in updates if isinstance(event, SessionInfoUpdate)] == ["My pending title"]


async def test_metadata_without_a_title_gives_the_session_no_coordination_title(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        agent = resumable_agent(workspace)
        with (
            patch.object(agent, "request", return_value=nullcontext()),
            patch("toad.acp.agent_session.api.session_new", return_value=Response(NewSessionResponse(sessionId="generic"))),
        ):
            await agent.session.new()
        assert agent.coordination is None
