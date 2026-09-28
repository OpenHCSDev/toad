"""Mounted cooperative default-root write admission, without a provider or live route.

Run with Toad src/tests and the paired PR116 source on PYTHONPATH. The
private root alone uses real /var/tmp because PR116's preflight requires it;
HOME, legacy wire and UI state remain disposable /dev/shm data.
"""

from __future__ import annotations

from toad.navigation_target import channel_target

from toad.thread_actions import StartAction
import asyncio
from contextlib import asynccontextmanager
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_comms.threads import Thread
from agent_comms.thread_identity import ThreadRole
from agent_comms import cohort_foreground
from agent_comms.active_route import ActiveRoute, publish_active_route
from agent_comms.comms import Comms
from agent_comms.private_nk_entrypoint import PACKAGE_ENV, ROOT_ID_ENV
from default_route_pilot import private_root

from toad.acp.maintenance_ingress import admitted_prompt, admitted_spawn
from toad.app import ToadApp
from toad.comms_root import current_root, run_selected_write
from toad.widgets.comms_chat import CommsChatView


@asynccontextmanager
async def settled_test_executor():
    """Finish read-only worker calls before deleting their disposable wire."""
    try:
        yield
    finally:
        await asyncio.get_running_loop().shutdown_default_executor()


async def main() -> None:
    if os.name != "posix" or Path("/var").is_symlink():
        raise RuntimeError("PR116 private publication needs real /var/tmp ancestry")
    with tempfile.TemporaryDirectory(
        prefix="toad-route-guard-", dir="/dev/shm"
    ) as directory:
        sandbox = Path(directory)
        sandbox.chmod(0o700)
        home = sandbox / "home"
        home.mkdir(mode=0o700)
        legacy = home / ".agent-comms"
        legacy.mkdir(mode=0o700)
        old = Comms(legacy)
        old.threads.register(Thread("user", frozenset(), str(sandbox), role=ThreadRole.USER))
        old.threads.register(Thread("peer", frozenset({"team"}), str(sandbox / "peer")))
        old.messaging.send("peer", "#team", "LEGACY-PAINT")
        with tempfile.TemporaryDirectory(
            prefix="toad-route-private-", dir="/var/tmp"
        ) as private_dir:
            private, private_id = private_root(
                Path(private_dir) / "wire", sandbox, "PRIVATE-PAINT"
            )
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
                assert current_root() == legacy
                app = ToadApp(project_dir=str(sandbox))
                async with settled_test_executor(), app.run_test(size=(115, 38)) as pilot:
                    await pilot.pause()
                    await app.open_comms_session(
                        owner_mode=app.current_mode,
                        project_path=sandbox,
                        me="user",
                        target=channel_target("#team"),

                    )
                    view = app.screen.query_one(CommsChatView)
                    await view._refresh()
                    await pilot.pause()
                    assert view._wire.root == legacy
                    old.messaging.send("peer", "#team", "UNREAD-OLD")
                    page = old.views.channel_display_page(
                        "#team", worktree=str(sandbox), limit=8
                    )
                    assert page.newest_seq == 2
                    marker = legacy / "read_markers.json"
                    before = marker.read_bytes() if marker.exists() else b""

                    entered_ack = asyncio.Event()
                    entered_action = asyncio.Event()
                    release = asyncio.Event()
                    original_to_thread = asyncio.to_thread
                    invoked: list[str] = []

                    async def delayed_dispatch(operation, *args, **kwargs):
                        if operation is run_selected_write:
                            name = getattr(args[1], "__name__", "")
                            if name == "mark_channel_view_read":
                                entered_ack.set()
                                await release.wait()
                            elif name == "safe_spy":
                                entered_action.set()
                                await release.wait()
                        return await original_to_thread(operation, *args, **kwargs)

                    def safe_spy(_action, ctx):
                        from agent_comms.owner_lifecycle import OwnerStartResult
                        invoked.append(ctx.subject)
                        return OwnerStartResult(ctx.subject, 0, False)

                    route = ActiveRoute(private, private_id, sandbox / "unused-package")
                    with (
                        patch("asyncio.to_thread", delayed_dispatch),
                        patch.object(StartAction, "apply", safe_spy),
                        patch.object(
                            cohort_foreground, "_trusted_package", lambda _: None
                        ),
                    ):
                        ack = asyncio.create_task(view._mark_painted_page(page))
                        app.invoke_thread_action(StartAction(), "peer", "user")
                        async with asyncio.timeout(8):
                            await entered_ack.wait()
                            await entered_action.wait()
                        # An in-flight ACP spawn holds the same route SH lock
                        # through process settlement. Publication cannot pass
                        # it; the delayed UI mutations have not acquired SH.
                        spawn_entered, release_spawn = asyncio.Event(), asyncio.Event()

                        async def fake_spawn(_command, **_kwargs):
                            spawn_entered.set()
                            await release_spawn.wait()
                            return SimpleNamespace(pid=123, returncode=0)

                        with patch("asyncio.create_subprocess_shell", fake_spawn):
                            spawn = asyncio.create_task(
                                admitted_spawn(
                                    "fake", env=dict(os.environ), cwd=str(sandbox)
                                )
                            )
                            async with asyncio.timeout(8):
                                await spawn_entered.wait()
                            publish = asyncio.get_running_loop().run_in_executor(
                                None, publish_active_route, route
                            )
                            assert not publish.done()
                            release_spawn.set()
                            await spawn
                            await publish
                        assert current_root() == private
                        release.set()
                        await ack
                        await pilot.pause()
                    assert (
                        not invoked
                    ), "stale old-root start reached its core operation"
                    assert (marker.read_bytes() if marker.exists() else b"") == before
                    assert not view.display or not view._wire.root == current_root()
                    try:
                        run_selected_write(
                            legacy, safe_spy, None, None, implicit=True
                        )
                    except ValueError:
                        pass
                    else:
                        raise AssertionError("stale old-root operation was admitted")

                    # Toad pins the exact selected private marker/package into
                    # an ACP child only after the SH guard has revalidated it.
                    observed_env = {}

                    async def observe_private(_command, **kwargs):
                        observed_env.update(kwargs["env"])
                        return SimpleNamespace(pid=123, returncode=0)

                    with patch("asyncio.create_subprocess_shell", observe_private):
                        await admitted_spawn(
                            "fake-private", env=dict(os.environ), cwd=str(sandbox)
                        )
                    assert observed_env["AGENT_COMMS_ROOT"] == str(private)
                    assert observed_env[ROOT_ID_ENV] == private_id
                    assert observed_env[PACKAGE_ENV] == str(route.native_package)
                    observed_env.clear()
                    poisoned = dict(os.environ, **{ROOT_ID_ENV: "f" * 32})
                    with patch("asyncio.create_subprocess_shell", observe_private):
                        try:
                            await admitted_spawn(
                                "wrong-private-id", env=poisoned, cwd=str(sandbox)
                            )
                        except ValueError as error:
                            assert "conflicts with route" in str(error)
                        else:
                            raise AssertionError(
                                "conflicting private child ID was launched"
                            )
                    assert not observed_env

                    # A caller-provided child root is explicit, even when
                    # Toad's own environment still uses the default route.
                    explicit_env = dict(os.environ, AGENT_COMMS_ROOT=str(legacy))
                    with patch("asyncio.create_subprocess_shell", observe_private):
                        await admitted_spawn(
                            "fake-explicit", env=explicit_env, cwd=str(sandbox)
                        )
                    assert observed_env["AGENT_COMMS_ROOT"] == str(legacy)
                    assert ROOT_ID_ENV not in observed_env
                    assert PACKAGE_ENV not in observed_env
                    observed_env.clear()
                    contradictory = dict(
                        explicit_env,
                        **{
                            ROOT_ID_ENV: private_id,
                            PACKAGE_ENV: str(route.native_package),
                        },
                    )
                    with patch("asyncio.create_subprocess_shell", observe_private):
                        try:
                            await admitted_spawn(
                                "explicit-legacy-with-private-flags",
                                env=contradictory,
                                cwd=str(sandbox),
                            )
                        except Exception as error:
                            assert "private" in str(error).lower()
                        else:
                            raise AssertionError(
                                "contradictory explicit child launched"
                            )
                    assert not observed_env
                    with admitted_prompt(
                        ingress_root=legacy, cwd=sandbox, implicit=False
                    ):
                        assert current_root() == private


if __name__ == "__main__":
    asyncio.run(main())
