"""Provider-free mounted default-route flip/reconnect/paint pilot.

Run with Toad src/tests and the paired PR116 agent-comms src on PYTHONPATH.
Only disposable private roots and an isolated HOME are used.
When /var/tmp lacks space, this non-durability UI pilot uses /dev/shm.
"""

from __future__ import annotations
from toad.navigation_target import NavigationContext

from toad.navigation_target import channel_target

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms.threads import Thread
from agent_comms.thread_identity import ThreadRole
from agent_comms.errors import HumanInitialUnknownError
from agent_comms.comms import Comms, wire

from toad import messages
from toad.acp.maintenance_ingress import barrier_for, configured_root
from toad.app import ToadApp
from toad.comms_root import (
    current_root,
    implicit_root,
    root_is_current,
    run_selected_write,
)
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_sidebar import CommsSidebar


def route(home: Path, root: Path, root_id: str) -> Path:
    directory = home / ".local/state/agent-comms"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    destination = directory / "active-route.json"
    temporary = directory / "replacement.json"
    temporary.write_text(
        json.dumps(
            {
                "version": 1,
                "root": str(root),
                "wire_root_id": root_id,
                "native_package": str(home / "unused-package"),
            }
        )
    )
    temporary.chmod(0o600)
    os.replace(temporary, destination)  # test-only controlled route flip
    return destination


def private_root(path: Path, project: Path, message: str) -> tuple[Path, str]:
    path.mkdir(mode=0o700)
    comms = Comms(path, private_initial_writes=True)
    comms.registry.declare(Thread("user", frozenset(), str(project), role=ThreadRole.USER))
    comms.registry.declare(Thread("owner", frozenset({"team"}), str(project / "owner-project")))
    comms.registry.declare(Thread("peer", frozenset({"team"}), str(project / "peer-project")))
    root_id = comms.messaging.initialize_private_initial_protocol()
    comms.messaging.send_initial_cohort("peer", "#team", message)
    return path, root_id


async def main() -> None:
    if os.name != "posix":
        raise RuntimeError("pilot needs POSIX private-root ancestry")
    real_tmp = Path("/var/tmp")
    enough_real_space = (
        not Path("/var").is_symlink()
        and real_tmp.stat().st_mode & 0o1000
        and os.statvfs(real_tmp).f_bavail * os.statvfs(real_tmp).f_frsize
        >= 512 * 1024 * 1024
    )
    disposable_base = real_tmp if enough_real_space else Path("/dev/shm")
    with tempfile.TemporaryDirectory(
        prefix="toad-route-", dir=disposable_base
    ) as directory:
        sandbox = Path(directory)
        sandbox.chmod(0o700)
        home = sandbox / "home"
        home.mkdir(mode=0o700)
        first, first_id = private_root(sandbox / "first", sandbox, "OLD-WIRE-ONLY")
        second, second_id = private_root(sandbox / "second", sandbox, "NEW-WIRE-ONLY")
        with patch.dict(
            os.environ,
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(sandbox / "config"),
                "XDG_DATA_HOME": str(sandbox / "data"),
                "XDG_STATE_HOME": str(sandbox / "state"),
            },
        ):
            os.environ.pop("AGENT_COMMS_ROOT", None)
            assert (
                current_root() == home / ".agent-comms"
            )  # absent route legacy default
            route_path = route(home, first, first_id)
            assert current_root() == first
            assert configured_root(os.environ, sandbox) == first
            assert barrier_for().registry_path == first / "registry.json"
            changed_home = dict(os.environ, HOME=str(sandbox / "another-home"))
            try:
                configured_root(changed_home, sandbox)
            except ValueError as error:
                assert "explicit child AGENT_COMMS_ROOT" in str(error)
            else:
                raise AssertionError("different child HOME selected the parent route")
            with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(second)}):
                assert current_root() == second
                assert configured_root(os.environ, sandbox) == second
                child_without_override = dict(os.environ)
                child_without_override.pop("AGENT_COMMS_ROOT")
                try:
                    configured_root(child_without_override, sandbox)
                except ValueError as error:
                    assert "explicit child AGENT_COMMS_ROOT" in str(error)
                else:
                    raise AssertionError(
                        "parent override leaked into an implicit child route"
                    )

            app = ToadApp(project_dir=str(sandbox))
            async with app.run_test(size=(115, 38)) as pilot:
                await pilot.pause()
                assert app.coordination_access.service.root == first
                owner_mode = app.selected_mode
                mode = await channel_target("#team").open(NavigationContext(app, owner_mode, sandbox, "user"))
                assert mode == app.selected_mode
                view = app.screen.query_one(CommsChatView)
                await view._refresh()
                await pilot.pause()
                assert view._wire.root == first
                assert any(
                    "OLD-WIRE-ONLY" in str(message) for message, _ in view._history
                ), view._history

                # A read already in flight when the route flips must not paint
                # a late page from the former wire into the successor view.
                view._wire.messaging.send_initial_cohort("peer", "#team", "LATE-OLD-EDGE")
                entered, release = asyncio.Event(), asyncio.Event()
                original_read = app.channel_history_reader.read

                async def delayed_read(*args, **kwargs):
                    entered.set()
                    await release.wait()
                    return await original_read(*args, **kwargs)

                with patch.object(app.channel_history_reader, "read", delayed_read):
                    view._revision = None
                    pending = asyncio.create_task(view._refresh())
                    async with asyncio.timeout(5):
                        await entered.wait()
                    route(home, second, second_id)
                    release.set()
                    await pending
                assert current_root() == second
                assert app.coordination_access.service.root == second  # app cache invalidated
                view.message_history.has_newer = True
                await view.message_history.load_edge()
                assert all(
                    "LATE-OLD-EDGE" not in str(message) for message, _ in view._history
                )
                await view._refresh()
                app.screen.query_one(CommsSidebar)._refresh()
                await pilot.pause()
                assert not root_is_current(first)
                assert (
                    not view.display and not app.screen.query_one(CommsSidebar).display
                )
                assert "OLD-WIRE-ONLY" not in app.export_screenshot()

            # A fresh UI connection paints only the newly published wire.
            new_app = ToadApp(project_dir=str(sandbox))
            async with new_app.run_test(size=(115, 38)) as pilot:
                await pilot.pause()
                assert new_app.coordination_access.service.root == second
                await channel_target("#team").open(NavigationContext(new_app, new_app.selected_mode, sandbox, "user"))
                new_view = new_app.screen.query_one(CommsChatView)
                await new_view._refresh()
                await pilot.pause()
                assert new_view.display and new_view._wire.root == second
                assert any(
                    "NEW-WIRE-ONLY" in str(message) for message, _ in new_view._history
                ), new_view._history
                assert all(
                    "OLD-WIRE-ONLY" not in str(message)
                    for message, _ in new_view._history
                )

                # A proven pre-append rejection remains editable; unlike an
                # UNKNOWN or an interrupted committed receipt, it is not a
                # non-retryable outcome.
                with patch.object(
                    new_view._wire.messaging, 'send_user_message',
                    side_effect=ValueError("pre-append admission rejected"),
                ) as rejected:
                    await new_view.submit_input(
                        messages.UserInputSubmitted("EDITABLE-REJECTION")
                    )
                    assert rejected.call_count == 1
                    assert new_view.prompt.text == "EDITABLE-REJECTION"
                    assert not new_view.prompt.prompt_text_area.disabled
                    assert not new_view._human_admission_blocked
                new_view.prompt.text = ""

                # An uncertain private send retains text for inspection and disables compose.
                error = HumanInitialUnknownError(second_id, 17, "opaque-unknown-id")
                with patch.object(
                    new_view._wire.messaging, "send_user_message", side_effect=error
                ) as sender:
                    event = messages.UserInputSubmitted("UNCERTAIN-NO-RETRY")
                    await new_view.submit_input(event)
                    assert sender.call_count == 1
                    assert new_view._unknown_send == (
                        second_id,
                        17,
                        "opaque-unknown-id",
                    )
                    assert new_view.prompt.text == event.body
                    assert new_view.prompt.prompt_text_area.disabled
                    await new_view.submit_input(event)
                    assert sender.call_count == 1
                route_path.write_text("{")
                route_path.chmod(0o600)
                await new_view._refresh()
                await pilot.pause()
                assert not new_view.display
                assert "NEW-WIRE-ONLY" not in new_app.export_screenshot()

            route_path.write_text("{")
            route_path.chmod(0o600)
            try:
                current_root()
            except ValueError:
                pass
            else:
                raise AssertionError("invalid route fell back to legacy")
            assert not root_is_current(second)
            route(home, second, first_id)
            try:
                current_root()
            except ValueError as error:
                assert "root ID" in str(error)
            else:
                raise AssertionError("route marker mismatch was accepted")
            route(home, second, second_id)
            route_path.chmod(0o644)
            try:
                current_root()
            except ValueError as error:
                assert "owner-only" in str(error)
            else:
                raise AssertionError("world-readable route was accepted")
            route_path.unlink()
            route_path.symlink_to(first / "bus_meta.json")
            try:
                current_root()
            except OSError, ValueError:
                pass
            else:
                raise AssertionError("symlink route was followed")
            assert wire(second).root == second  # explicit root bypasses broken route
            with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(second)}):
                assert (
                    run_selected_write(
                        second,
                        lambda: "explicit-root-operation",
                        implicit=implicit_root(),
                    )
                    == "explicit-root-operation"
                )


if __name__ == "__main__":
    asyncio.run(main())
