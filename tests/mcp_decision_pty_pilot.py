"""Fake-package, provider-free genuine PTY decision and stale/timeout fences."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static

import toad.mcp_decision as decisions
from toad.mcp_decision import Decision, DecisionAction, LocalDecisionPTY
from toad.mcp_inventory import parse_inventory
from toad.screens.mcp_decision import MCPDecisionScreen
from toad.screens.mcp_inventory import MCPInventoryScreen


DIGEST = "a" * 64


def fixture(root: Path) -> dict:
    return {
        "version": 2,
        "projectRoot": str(root),
        "projectTrustedSaved": True,
        "projectConfigSkipped": False,
        "lifetime": "active_pi_turn",
        "live": {"state": "not_running"},
        "declarations": {
            "user": [],
            "project": [
                {
                    "id": "fixture",
                    "scope": "project",
                    "digest": DIGEST,
                    "effective": True,
                    "enabled": True,
                    "status": "approved",
                    "callPolicy": "ask",
                    "transport": {
                        "type": "stdio",
                        "cwd": "project",
                        "argumentCount": 0,
                        "envNames": [],
                        "envFrom": [],
                    },
                }
            ],
        },
    }


async def main() -> None:
    if os.name != "posix":
        print("POSIX-only MCP PTY pilot skipped")
        return
    with TemporaryDirectory(prefix="toad-mcp-pty-") as directory:
        root = Path(directory).resolve()
        original = fixture(root)
        inventory = parse_inventory(json.dumps(original).encode(), root)
        row = inventory.project[0]
        marker, stale = root / "action-marker", root / "stale"
        script = root / "fake-package-cli.py"
        script.write_text(
            """\
import json, os, pathlib, sys, time
ROOT = pathlib.Path(ROOT_VALUE)
DOC = DOC_VALUE
args = sys.argv[1:]
if args[0] == 'inventory':
    assert args == ['inventory', '--json', '--project', str(ROOT)]
    if (ROOT / 'slow').exists():
        time.sleep(0.3)
    if (ROOT / 'stale').exists():
        DOC['declarations']['project'][0]['transport']['argumentCount'] = 1
    print(json.dumps(DOC))
else:
    action, decision = args[:2]
    assert (action, decision) in [
        ('trust', 'approve'), ('trust', 'deny'), ('calls', 'allow'), ('calls', 'ask')
    ]
    assert args[2:] == ['--id', 'fixture', '--digest', DIGEST_VALUE, '--project', str(ROOT)]
    assert os.isatty(0) and os.isatty(1), 'A real PTY is required'
    print('Full local approval display: fixture / digest', flush=True)
    print('Type ' + decision + ':fixture:' + DIGEST_VALUE + ' to apply: ', end='', flush=True)
    answer = sys.stdin.readline().rstrip('\\r\\n')
    if answer != decision + ':fixture:' + DIGEST_VALUE:
        sys.exit(1)
    (ROOT / 'action-marker').write_text('user typed challenge:' + action)
    print('Package receipt: next_pi_turn', flush=True)
""".replace("ROOT_VALUE", repr(str(root)))
            .replace("DOC_VALUE", repr(original))
            .replace("DIGEST_VALUE", repr(DIGEST))
        )
        assert not marker.exists()
        pty = LocalDecisionPTY()
        displayed: list[str] = []
        appeared = asyncio.Event()

        async def show(text: str) -> None:
            displayed.append(text)
            if "to apply" in "".join(displayed):
                appeared.set()

        def visible() -> bool:
            return True

        async def attempt(
            action: DecisionAction = "trust", decision: Decision = "deny"
        ) -> str:
            return await pty.run(
                inventory=inventory,
                row=row,
                action=action,
                decision=decision,
                node_path=sys.executable,
                cli_path=str(script),
                show=show,
                controller_visible=visible,
            )

        # No stale snapshot may reach the action branch of the fake CLI.
        stale.touch()
        assert await attempt() == "stale_snapshot"
        assert not marker.exists()
        stale.unlink()
        assert (
            await pty.run(
                inventory=inventory,
                row=row,
                action="trust",
                decision="deny",
                node_path=sys.executable,
                cli_path=str(script),
                show=show,
                controller_visible=lambda: False,
            )
            == "unavailable"
        )
        assert not marker.exists()
        assert (
            await pty.run(
                inventory=inventory,
                row=row,
                action="calls",
                decision="bogus",  # type: ignore[arg-type]
                node_path=sys.executable,
                cli_path=str(script),
                show=show,
                controller_visible=visible,
            )
            == "unsupported"
        )
        assert not marker.exists()
        assert (
            await pty.run(
                inventory=inventory,
                row=row,
                action="trust",
                decision="deny",
                node_path="",
                cli_path=str(script),
                show=show,
                controller_visible=visible,
            )
            == "unavailable"
        )
        assert not marker.exists()

        runner = asyncio.create_task(attempt())
        await asyncio.wait_for(appeared.wait(), 3)
        assert "Full local approval display" in "".join(displayed)
        assert not marker.exists(), "UI auto-answered a challenge"
        # The only input is explicitly supplied through the terminal's user path.
        await pty.write_user_input(f"deny:fixture:{DIGEST}\n")
        assert await asyncio.wait_for(runner, 3) == "exited_zero"
        assert marker.read_text() == "user typed challenge:trust"
        marker.unlink()
        appeared.clear()
        displayed.clear()
        ask_runner = asyncio.create_task(attempt("calls", "ask"))
        await asyncio.wait_for(appeared.wait(), 3)
        assert not marker.exists()
        await pty.write_user_input(f"ask:fixture:{DIGEST}\n")
        assert await asyncio.wait_for(ask_runner, 3) == "exited_zero"
        assert marker.read_text() == "user typed challenge:calls"
        marker.unlink()
        appeared.clear()
        displayed.clear()
        allow_runner = asyncio.create_task(attempt("calls", "allow"))
        await asyncio.wait_for(appeared.wait(), 3)
        assert not marker.exists()
        await pty.write_user_input(f"allow:fixture:{DIGEST}\n")
        assert await asyncio.wait_for(allow_runner, 3) == "exited_zero"
        assert marker.read_text() == "user typed challenge:calls"
        marker.unlink()
        appeared.clear()
        displayed.clear()
        approve_runner = asyncio.create_task(attempt("trust", "approve"))
        await asyncio.wait_for(appeared.wait(), 3)
        assert not marker.exists()
        await pty.write_user_input(f"approve:fixture:{DIGEST}\n")
        assert await asyncio.wait_for(approve_runner, 3) == "exited_zero"
        assert marker.read_text() == "user typed challenge:trust"
        marker.unlink()
        appeared.clear()
        displayed.clear()
        timeout_before = decisions.DECISION_TIMEOUT_SECONDS
        decisions.DECISION_TIMEOUT_SECONDS = 0.04
        try:
            assert await attempt() == "timeout"
        finally:
            decisions.DECISION_TIMEOUT_SECONDS = timeout_before
        assert not marker.exists()

        # The actual Textual modal must render output, then cancel its child
        # when the visible controller goes away (no challenge sent).
        class DecisionApp(App):
            def compose(self) -> ComposeResult:
                yield Static("Home")

        app = DecisionApp()
        async with app.run_test(size=(100, 32)) as pilot:
            screen = MCPDecisionScreen(
                inventory,
                row,
                action="trust",
                decision="deny",
                node_path=sys.executable,
                cli_path=str(script),
            )
            app.push_screen(screen)
            await pilot.pause(0.2)
            assert app.screen is screen
            assert screen._pty._process is not None
            assert not marker.exists()
            screen.action_close_decision()
            await pilot.pause(0.1)
            assert app.screen is not screen
            assert not marker.exists()
            slow = root / "slow"
            slow.touch()
            hidden = MCPDecisionScreen(
                inventory,
                row,
                action="trust",
                decision="deny",
                node_path=sys.executable,
                cli_path=str(script),
            )
            app.push_screen(hidden)
            await pilot.pause(0.02)
            hidden.action_close_decision()
            await pilot.pause(0.4)
            assert app.screen is not hidden and not marker.exists()
            slow.unlink()

            class Cover(ModalScreen[None]):
                def compose(self) -> ComposeResult:
                    yield Static("Covered")

            obscured = MCPDecisionScreen(
                inventory,
                row,
                action="trust",
                decision="deny",
                node_path=sys.executable,
                cli_path=str(script),
            )
            app.push_screen(obscured)
            await pilot.pause(0.2)
            child = obscured._pty._process
            assert child is not None and child.returncode is None
            cover = Cover()
            app.push_screen(cover)
            await pilot.pause(0.15)
            assert child.returncode is not None, (
                "Hidden controller left decision child running"
            )
            cover.dismiss()
            await pilot.pause(0.05)
            assert "may have committed" in str(
                obscured.query_one("#mcp-decision-status", Static).content
            )
            obscured.dismiss()
            await pilot.pause(0.05)
            inventory_screen = MCPInventoryScreen(
                root, node_path=sys.executable, cli_path=str(script)
            )
            app.push_screen(inventory_screen)
            await pilot.pause(0.15)
            assert app.screen is inventory_screen
            inventory_screen.query_one(
                "#mcp-inventory-rows", OptionList
            ).highlighted = 0
            await pilot.pause(0.02)
            assert not inventory_screen.query_one("#trust_deny", Button).disabled
            assert not inventory_screen.query_one("#calls_ask", Button).disabled
            assert not inventory_screen.query_one("#trust_approve", Button).disabled
            assert not inventory_screen.query_one("#calls_allow", Button).disabled
            inventory_screen.query_one("#trust_deny", Button).press()
            await pilot.pause(0.2)
            assert isinstance(app.screen, MCPDecisionScreen)
            assert not marker.exists()
            app.screen.action_close_decision()
            await pilot.pause(0.1)
            assert app.screen is inventory_screen and not marker.exists()
            inventory_screen.dismiss()
            await pilot.pause(0.05)
            assert app._exception is None
    print(
        "MCP PTY: visible real TTY, typed digest, no auto-answer, stale/timeout/cancel fences"
    )


if __name__ == "__main__":
    asyncio.run(main())
