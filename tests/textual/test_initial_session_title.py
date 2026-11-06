"""Textual-facing: the title in a new ACP session's first metadata names the tab (a Textual tab label) and the saved session without switching tabs."""

from contextlib import nullcontext
from unittest.mock import AsyncMock, patch

import pytest
from acp.schema import AgentCapabilities, InitializeResponse, LoadSessionResponse, NewSessionResponse
from agent_comms.acp_extension import encode_updates

from support.agents import command
from support.coordination import coordination_fact
from toad.acp.agent import Agent
from toad.core.events import CoreEvent, SessionInfoUpdate
from toad.db import DB

THREAD = "existing-worker"


class Recorder:
    """A bound listener, because a subscription names a method rather than a function."""

    def __init__(self):
        self.events = []

    def receive(self, event, subscription):
        self.events.append(event)


class StubConnection:
    """The SDK connection an agent sees, answering the session requests a test fixes."""

    def __init__(self, new=None, load=None):
        self.new, self.load = new, load
        self.loaded_sessions: list[str] = []

    async def new_session(self, cwd, mcp_servers):
        return self.new

    async def load_session(self, cwd, session_id, mcp_servers, **metadata):
        self.loaded_sessions.append(session_id)
        return self.load

    async def close(self):
        pass


def resumable_agent(ui, workspace, session_id=None, session_pk=None):
    """An agent object with no process whose handshake advertises session loading."""
    access = ui.textual[0].coordination_access
    agent = Agent(workspace.project, command("false", name="fixture", identity="agent-comms.openhcs.dev"),
                  session_id, session_pk,
                  app_events=access.events, transcripts=access.transcripts)
    agent.process.connection = StubConnection()
    agent.process.initialization = InitializeResponse(
        protocolVersion=1, agentCapabilities=AgentCapabilities(loadSession=True))
    return agent


def metadata(workspace, title):
    return encode_updates(coordination_fact(workspace.comms, THREAD, title=title, worktree=workspace.project))


def tab_title(ui, identity):
    return next(tab.title for tab in ui.tabs() if tab.identity == identity)


def tab_identity(ui, mode_name):
    """The tracker's identity for the tab carrying this mode name."""
    app = ui.textual[0]
    return next(identity for identity, details in app.session_tracker.sessions.items()
                if details.mode_name == mode_name)


def displayed_name(ui, identity):
    """The saved name of the tab carrying this mode name."""
    app = ui.textual[0]
    return next(details.name.display
                for details in app.session_tracker.sessions.values()
                if details.mode_name == identity)


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
        agent = resumable_agent(ui, workspace)
        ui.attach_agent(agent)
        agent.process.connection.new = created
        with patch.object(DB, "session_new", new=record_creation):
            await agent.session.new()
        await ui.until(lambda: expected in tab_title(ui, mode), why="the tab to carry the thread's title")
        assert created_titles == [expected], ("saved title at creation", created_titles, expected)
        assert ui.selected_tab == mode, "No tab switch should be needed"
        await ui.until(lambda: displayed_name(ui, mode) == expected, why="the saved session to carry the thread's title")
        assert agent.session.pk is not None
        assert (await DB().session_get(agent.session.pk)).title == expected
        recorded = workspace.comms.registry.require(THREAD).title
        assert getattr(recorded, "text", None) == title, "Presenting a title must not rename the thread"


@pytest.mark.parametrize("title", ["An already named thread", None], ids=["named", "unnamed"])
async def test_loading_a_saved_session_names_its_tab_and_keeps_an_explicit_label(workspace, title):
    expected = title or THREAD
    workspace.thread(THREAD, "acp", title=title)
    meta = metadata(workspace, title)
    created, loaded_response = NewSessionResponse(sessionId=THREAD, _meta=meta), LoadSessionResponse(_meta=meta)
    async with workspace.app(size=(120, 40)) as ui:
        app, _pilot = ui.textual
        agent = resumable_agent(ui, workspace)
        ui.attach_agent(agent)
        agent.process.connection.new = created
        await agent.session.new()
        loaded = await ui.new_session()
        resumed = resumable_agent(ui, workspace, THREAD, agent.session.pk)
        ui.attach_agent(resumed)
        resumed.process.connection.load = loaded_response
        await resumed.session.load()
        await ui.until(lambda: expected in tab_title(ui, loaded), why="the loaded tab to carry the thread's title")
        assert ui.selected_tab == loaded
        assert displayed_name(ui, loaded) == expected
        assert (await DB().session_get(agent.session.pk)).title == expected
        app.session_tracker.name_session(tab_identity(ui, loaded), "My explicit label")
        assert displayed_name(ui, loaded) == "My explicit label"
        resumed.comms_consumer_class(resumed, resumed.session_id).dispatch_sync(
            coordination_fact(workspace.comms, THREAD))
        await ui.step()
        assert displayed_name(ui, loaded) == "My explicit label"


async def new_session_with_pending_name(ui, workspace):
    workspace.thread(THREAD, "acp")
    created =NewSessionResponse(sessionId=THREAD, _meta=metadata(workspace, None))
    agent = resumable_agent(ui, workspace)
    agent.session.chosen_name = "My pending title"
    saved = AsyncMock(return_value=7)
    updates = Recorder()
    agent.process.connection.new = created
    with (
        patch.object(DB, "session_new", new=saved),
        patch.object(DB, "session_update_title", new=AsyncMock()),
        patch.object(agent, "rename_coordination"),
        agent.events.subscribe(CoreEvent, updates.receive),
    ):
        await agent.session.new()
    return saved, updates


async def test_a_name_chosen_before_the_session_exists_is_saved_with_the_session(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        saved, _updates = await new_session_with_pending_name(ui, workspace)
        assert saved.call_args.args[0] == "My pending title"


async def test_a_name_chosen_before_the_session_exists_is_announced_as_its_title(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        _saved, updates = await new_session_with_pending_name(ui, workspace)
        assert [event.title for event in updates.events if isinstance(event, SessionInfoUpdate)] == ["My pending title"]


async def test_metadata_without_a_title_gives_the_session_no_coordination_title(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        agent = resumable_agent(ui, workspace)
        agent.process.connection.new = NewSessionResponse(sessionId="generic")
        await agent.session.new()
        assert agent.coordination is None


async def test_a_reopened_tab_keeps_the_label_it_was_saved_with(workspace):
    """The wire presents the thread's title; it must not rewrite a saved tab label.

    A reader who renamed a tab saw the name change back the moment Toad connected,
    because the session adopted the thread's title over its own saved one.
    """
    workspace.thread(THREAD, "acp", title=None)
    meta = metadata(workspace, None)
    async with workspace.app(size=(120, 40)) as ui:
        agent = resumable_agent(ui, workspace)
        ui.attach_agent(agent)
        agent.process.connection.new = NewSessionResponse(sessionId=THREAD, _meta=meta)
        await agent.session.new()
        await ui.until(lambda: agent.session.pk is not None, why="the session row to exist")
        await DB().session_update_title(agent.session.pk, "Renamed by the reader")

        reopened = resumable_agent(ui, workspace, THREAD, agent.session.pk)
        ui.attach_agent(reopened)
        reopened.process.connection.load = LoadSessionResponse(_meta=meta)
        await reopened.session.load()
        reopened.session.coordinated_title(THREAD)
        await ui.step()
        assert (await DB().session_get(agent.session.pk)).title == "Renamed by the reader", (
            "Connecting must not rewrite the tab label the reader chose"
        )
