"""New/load SDK metadata names the visible tab and its real saved session."""
import os
import sys

import pytest
from acp.schema import NewSessionResponse
from agent_comms.acp_extension import encode_updates
from agent_comms.child_process import ProcessIdentity

from support.agents import AppAgents, PEERS, RecordedEvents, command, deliver
from support.coordination import carrying, registered_coordination_fact
from toad.acp.agent import Agent
from toad.core.events import CoreEvent, SessionInfoUpdate
from toad.db import DB

THREAD = "existing-worker"


def response_peer(workspace, response: NewSessionResponse):
    """An actual SDK response supplied to the real stdio peer."""
    path = workspace.project / "title-session-response.json"
    path.write_text(response.model_dump_json(by_alias=True))
    return command(sys.executable, str(PEERS / "resumable_session_response.py"), str(path),
                   name="Title response peer", identity="title-response-peer")


def named_peer(workspace, title=None):
    """The scratch registry owns the response's real incarnation and process."""
    workspace.thread(THREAD, "acp", running=True, title=title)
    fact = registered_coordination_fact(
        workspace.comms, THREAD, title=title, worktree=workspace.project,
        owner=ProcessIdentity.capture(os.getpid()),
    )
    return response_peer(workspace, NewSessionResponse(sessionId=THREAD, _meta=encode_updates(fact)))


async def start(ui, definition, *, session_id=None, session_pk=None, name=None):
    agent = AppAgents(ui.app).agent(Agent, definition, session_id, session_pk=session_pk)
    agent.session.chosen_name = name
    ui.attach_agent(agent)
    await agent.start()
    await ui.until(lambda: agent.ready, why="the actual SDK title handshake")
    return agent


def tab_title(ui, identity):
    return next(tab.title for tab in ui.tabs() if tab.identity == identity)


@pytest.mark.parametrize("title", ["An already named thread", None], ids=["named", "unnamed"])
async def test_new_session_metadata_names_the_tab_and_the_saved_session(workspace, title):
    expected = title or THREAD
    definition = named_peer(workspace, title=title)
    async with workspace.app(size=(120, 40)) as ui:
        mode = ui.selected_tab
        agent = await start(ui, definition)
        await ui.until(lambda: expected in tab_title(ui, mode), why="the first metadata title")
        assert ui.selected_tab == mode
        assert ui.app.session_tracker.get_session(mode).name.display == expected
        assert agent.session.pk is not None
        assert (await DB().session_get(agent.session.pk)).title == expected
        assert workspace.comms.registry.require(THREAD).title.otherwise(None) == title


@pytest.mark.parametrize("title", ["An already named thread", None], ids=["named", "unnamed"])
async def test_loading_a_saved_session_names_its_tab_and_keeps_an_explicit_label(workspace, title):
    expected = title or THREAD
    definition = named_peer(workspace, title=title)
    async with workspace.app(size=(120, 40)) as ui:
        agent = await start(ui, definition)
        loaded = await ui.new_session()
        resumed = await start(ui, definition, session_id=THREAD, session_pk=agent.session.pk)
        await ui.until(lambda: expected in tab_title(ui, loaded), why="the loaded metadata title")
        assert ui.selected_tab == loaded
        assert ui.app.session_tracker.get_session(loaded).name.display == expected
        assert (await DB().session_get(agent.session.pk)).title == expected
        ui.app.session_tracker.name_session(loaded, "My explicit label")
        await deliver(resumed, carrying(registered_coordination_fact(
            workspace.comms, THREAD, owner=ProcessIdentity.capture(os.getpid()),
            worktree=workspace.project,
        )))
        await ui.step()
        assert ui.app.session_tracker.get_session(loaded).name.display == "My explicit label"


async def test_a_name_chosen_before_the_session_exists_is_saved_with_the_session(workspace):
    definition = named_peer(workspace)
    async with workspace.app(size=(120, 40)) as ui:
        agent = await start(ui, definition, name="My pending title")
        assert agent.session.pk is not None
        assert (await DB().session_get(agent.session.pk)).title == "My pending title"


async def test_a_name_chosen_before_the_session_exists_is_announced_as_its_title(workspace):
    definition = named_peer(workspace)
    async with workspace.app(size=(120, 40)) as ui:
        agent = AppAgents(ui.app).agent(Agent, definition)
        agent.session.chosen_name = "My pending title"
        ui.attach_agent(agent)
        updates = RecordedEvents()
        with agent.events.subscribe(CoreEvent, updates.receive):
            await agent.start()
            await ui.until(lambda: agent.ready, why="the chosen-title SDK handshake")
        assert [event.title for event in updates if isinstance(event, SessionInfoUpdate)] == ["My pending title"]


async def test_metadata_without_a_title_gives_the_session_no_coordination_title(workspace):
    definition = response_peer(workspace, NewSessionResponse(sessionId=THREAD))
    async with workspace.app(size=(120, 40)) as ui:
        agent = await start(ui, definition)
        assert not agent.presentation.queue_supported
        assert (await DB().session_get(agent.session.pk)).title == "New Session"
