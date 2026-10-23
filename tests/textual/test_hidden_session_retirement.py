"""Textual-facing: hidden native sessions cost no repeated Core reads or completion-list rebuilds while idle, and retire only when their own thread is gone."""

from collections import Counter
from pathlib import Path
import sys

from agent_comms.comms import Comms
from agent_comms.registry_store import RegistryStore
from agent_comms.threads import Thread
from textual.widgets import OptionList

from support.roots import installed_wire

from toad.core.events import CoordinationObserved
from toad.screens.main import MainScreen
from toad.target_commands import TargetContext
from toad.widgets.conversation import Conversation
from toad.tab_identity.kinds import MailboxTab


def declare_owners(workspace):
    owners = []
    for number in range(4):
        path = workspace.project if number == 0 else workspace.project / f"agent-{number}"
        path.mkdir(exist_ok=True)
        owners.append(workspace.comms.registry.declare(Thread(
            "project" if number == 0 else f"agent-{number}", frozenset({"team"}), str(path))))
    return owners


async def open_hidden_sessions(workspace, ui, owners):
    app, _ = ui.textual
    first = ui.selected_tab

    def source(owner):
        return MainScreen.from_thread(Path(owner.worktree), str(workspace.comms.root), owner.incarnation)

    modes = {}
    for owner in owners[1:]:
        details = await app.session_navigation.new(
            MailboxTab(owner.incarnation, str(workspace.comms.root)),
            lambda owner=owner: source(owner), original=(str(workspace.comms.root), owner.incarnation))
        modes[owner.name] = details.mode_name
    await ui.select_tab(first)
    await app.session_navigation.retire_missing()
    await ui.step()
    return modes


async def test_idle_retirement_passes_read_nothing_and_a_hidden_prompt_skips_discovery(workspace):
    owners = declare_owners(workspace)
    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        modes = await open_hidden_sessions(workspace, ui, owners)
        observed = app.coordination_access.observation.observed()
        calls = Counter()
        watched = {Comms.__init__.__code__: "service_constructions",
                   RegistryStore._decode.__code__: "registry_decodes",
                   TargetContext.available_actions.__code__: "action_discovery",
                   OptionList.set_options.__code__: "option_rebuilds"}
        monitor = sys.monitoring
        monitor.use_tool_id(monitor.PROFILER_ID, "navigation-lifetime")
        monitor.register_callback(monitor.PROFILER_ID, monitor.events.PY_START,
                                  lambda code, offset: calls.update((watched[code],)))
        for code in watched:
            monitor.set_local_events(monitor.PROFILER_ID, code, monitor.events.PY_START)
        try:
            for _ in range(4):
                await app.session_navigation.retire_missing()
                app.coordination_access.events.publish(CoordinationObserved(None))
                await ui.step()
            assert app.coordination_access.observation.observed() is observed
            assert calls["service_constructions"] == calls["registry_decodes"] == 0
            assert calls["action_discovery"] == calls["option_rebuilds"] == 0
            before = calls["action_discovery"]
            hidden = app.workspace_sessions.views[modes["agent-1"]]
            await hidden.query_one(Conversation).update_slash_commands().wait()
            assert calls["action_discovery"] == before, "a hidden prompt queried the backend"
            await ui.select_tab(hidden.id)
            await hidden.query_one(Conversation).update_slash_commands().wait()
            assert calls["action_discovery"] > before, "the selected prompt did not discover its actions"
            conversation = hidden.query_one(Conversation)
            popup = conversation.prompt.slash_complete
            before = calls["option_rebuilds"]
            conversation.prompt.slash_commands = list(conversation.prompt.slash_commands)
            await ui.step()
            assert calls["option_rebuilds"] == before
            conversation.prompt.focus()
            await ui.press("/")
            await conversation.update_slash_commands().wait()
            await ui.step()
            assert popup.is_open and popup.option_list.option_count > 0
            assert calls["option_rebuilds"] > before
            await ui.press("escape")
            assert not popup.is_open
            assert conversation.prompt.prompt_text_area.text == "/"
        finally:
            for code in watched:
                monitor.set_local_events(monitor.PROFILER_ID, code, 0)
            monitor.free_tool_id(monitor.PROFILER_ID)


async def test_a_renamed_thread_keeps_its_hidden_session(workspace):
    owners = declare_owners(workspace)
    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        modes = await open_hidden_sessions(workspace, ui, owners)
        _, renamed = app.session_navigation.get(modes["agent-2"]).original_threads(app.session_navigation)[0]
        workspace.comms.registry.rename(renamed.name, "renamed-agent")
        await app.session_navigation.retire_missing()
        assert app.session_navigation.get(modes["agent-2"]) is not None


async def test_a_same_name_successor_does_not_keep_the_deleted_threads_hidden_session(workspace):
    owners = declare_owners(workspace)
    registry = workspace.comms.registry
    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        modes = await open_hidden_sessions(workspace, ui, owners)
        _, gone = app.session_navigation.get(modes["agent-3"]).original_threads(app.session_navigation)[0]
        old = registry.require(gone.name)
        registry.unregister(old.name)
        registry.remove_originals((registry.require(old.name),))
        registry.declare(Thread(old.name, old.tags, old.worktree, created_at=old.created_at + 1))
        await app.session_navigation.retire_missing()
        await ui.until(lambda: app.session_navigation.get(modes["agent-3"]) is None, seconds=15,
                       why="the deleted thread's hidden session to retire")


async def test_an_ambient_root_change_does_not_retire_a_hidden_thread(workspace, monkeypatch):
    owners = declare_owners(workspace)
    async with workspace.app(size=(140, 48)) as ui:
        app, _ = ui.textual
        modes = await open_hidden_sessions(workspace, ui, owners)
        other = installed_wire(workspace.roots.wire.parent / "other")
        monkeypatch.setenv("AGENT_COMMS_ROOT", str(other.root))
        await app.session_navigation.retire_missing()
        assert app.session_navigation.get(modes["agent-2"]) is not None
