"""The MCP inventory screen reads the native package's inventory and applies trust decisions through
the package's own command in a terminal dialog."""

from copy import deepcopy
import json
import subprocess

from textual import events
from textual.widgets import Button, OptionList, Static

from support.native import start_private_native_wire
from support.native_mcp import declare_fixture_server
from support.textual_steps import viewport_text
from toad.mcp_commands import AllowCommand, MCPDecision, MCPSelection, ProjectTrustDecision
from toad.mcp_decision import LocalDecisionPTY
from toad.mcp_declarations import AllowPolicy, ApprovedStatus, AskPolicy, DeniedStatus
from toad.mcp_inventory import UnsupportedInventory, installed_mcp_command, parse_inventory
from toad.mcp_outcomes import StaleSnapshotOutcome
from toad.screens.mcp_decision import MCPDecisionScreen
from toad.screens.mcp_inventory import MCPDecisionButton, MCPInventoryScreen
from toad.widgets.terminal import Terminal


class ApproveAgainCommand(ProjectTrustDecision):
    """A decision declared here: the screen must offer and apply it with no other edit."""

    label = "Approve again"

    def arguments(self):
        return "trust", "approve"


def package_inventory(project) -> bytes:
    node, cli = installed_mcp_command()
    return subprocess.run([node, cli, "inventory", "--json", "--project", str(project)],
                          check=True, capture_output=True, timeout=10).stdout


def test_inventory_from_the_package_is_decoded_and_malformed_inventory_refused(workspace, native_package):
    start_private_native_wire(workspace.roots.wire)
    agent_dir = workspace.roots.attempt / "pi"
    agent_dir.mkdir(mode=0o700, exist_ok=True)
    declare_fixture_server(native_package, workspace.project, agent_dir, trusted=False)
    raw = package_inventory(workspace.project)
    untrusted = parse_inventory(raw, workspace.project)
    assert not untrusted.project_trusted_saved and not untrusted.declarations.project
    malformed = []
    for path, bad in (
        (("version",), True), (("projectRoot",), str(workspace.project / "not-canonical")),
        (("live", "state"), "running"),
        (("declarations", "user", 0, "transport", "argumentCount"), True),
        (("declarations", "user", 0, "transport", "envFrom"), [["CHILD"]]),
        (("declarations", "user", 0, "scope"), "project"),
        (("declarations", "user", 0, "callPolicy"), "allow"),
        (("declarations", "user", 0, "executable"), "SECRET"),
    ):
        changed = deepcopy(json.loads(raw))
        target = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = bad
        malformed.append(json.dumps(changed).encode())
    malformed.extend((raw.replace(b'"version":2', b'"version":2,"version":2'), b'{"version":2,', b" " * 128_001))
    for data in malformed:
        try:
            parse_inventory(data, workspace.project)
        except UnsupportedInventory:
            continue
        raise AssertionError(f"Malformed inventory accepted: {data[:120]!r}")


async def test_trust_decisions_are_applied_through_the_terminal_dialog(workspace, native_package):
    start_private_native_wire(workspace.roots.wire)
    project = workspace.project
    agent_dir = workspace.roots.attempt / "pi"
    agent_dir.mkdir(mode=0o700, exist_ok=True)
    declare_fixture_server(native_package, project, agent_dir, trusted=False)
    async with workspace.app(size=(160, 44)) as ui:
        app, pilot = ui.textual

        def project_row(inventory):
            return next(row for row in inventory.rows if row.scope.declared_name == "project")

        def terminal_text(terminal):
            return "\n".join(line.content.plain for line in terminal.state.buffer.lines)

        await ui.press("ctrl+p")
        await ui.press(*"Pi MCP inventory")
        await ui.press("enter")
        await ui.until(lambda: isinstance(app.screen, MCPInventoryScreen), why="the MCP inventory screen")
        screen = app.screen
        await ui.until(lambda: screen._inventory is not None, why="the inventory")
        listing = screen.query_one(OptionList)

        async def select_project_row():
            listing.focus()
            await ui.press("end")

        async def refreshed():
            await ui.until(lambda: app.screen is screen and screen._inventory is not None, why="the refreshed inventory")

        async def apply(command, row):
            """Click the decision, type the challenge the package asks for, and wait for it to be applied."""
            assert await pilot.click(f"#{command.button_id}")
            await ui.until(lambda: isinstance(app.screen, MCPDecisionScreen), why="the decision dialog")
            modal = app.screen
            terminal = modal.query_one(Terminal)
            await ui.until(lambda: " to apply:" in terminal_text(terminal), why="the package's challenge")
            await ui.step()
            assert command.arguments()[1] in viewport_text(terminal)
            assert "never-launched" in viewport_text(terminal)
            terminal.focus()
            app._driver.send_message(events.Paste(f"{command.arguments()[1]}:{row.id}:{row.digest}"))
            await ui.step()
            await ui.press("enter")
            await ui.until(lambda: "CLI exited zero" in viewport_text(modal.query_one("#mcp-decision-status", Static)),
                           why="the package command to succeed")
            process = await modal._pty.process()
            assert process.master.closed and process.child.retired
            assert await pilot.click("#cancel")
            await refreshed()
            return terminal

        listing.focus()
        await ui.press("down")
        assert all(button.disabled for button in screen.query(MCPDecisionButton))
        assert "trust_required" in viewport_text(listing)
        assert "HIDDEN_ARGUMENT" not in viewport_text(screen)

        declare_fixture_server(native_package, project, agent_dir, trusted=True)
        assert await pilot.click("#refresh")
        await ui.until(lambda: screen._inventory is not None and screen._inventory.project_trusted_saved,
                       why="the trusted project's inventory")
        await select_project_row()
        assert not screen.query_one("#approve", Button).disabled
        assert screen.query_one("#allow", Button).disabled
        assert "shadowed" in viewport_text(listing)
        assert "Approve again" in viewport_text(screen)

        terminal = None
        for member in MCPDecision.members_with(MCPDecision):
            command = member()
            await select_project_row()
            assert not screen.query_one(f"#{command.button_id}", Button).disabled
            terminal = await apply(command, project_row(screen._inventory))
            changed = project_row(screen._inventory)
            expected = {"approve": ApprovedStatus, "deny": DeniedStatus}.get(command.declared_name)
            if expected is not None:
                assert changed.status is expected, terminal_text(terminal)
            if changed.status is DeniedStatus:
                # Approve again so the call-policy decisions that follow are available.
                await select_project_row()
                approve = next(member() for member in MCPDecision.members_with(MCPDecision)
                               if member().button_id == "approve")
                await apply(approve, changed)
            if command.declared_name == "ask":
                assert changed.call_policy is AskPolicy
            if command.declared_name == "allow":
                assert changed.call_policy is AllowPolicy

        # A decision taken on an inventory that has since changed is refused before anything is started.
        earlier = screen._inventory
        earlier_row = project_row(earlier)
        declare_fixture_server(native_package, project, agent_dir, trusted=False)

        async def nothing_may_start(_text):
            raise AssertionError("A decision on a changed inventory started the package command")

        outcome = await LocalDecisionPTY(lambda: True).run(
            selection=MCPSelection(earlier, earlier_row), command=AllowCommand(),
            show=nothing_may_start, state=terminal.state)
        assert isinstance(outcome, StaleSnapshotOutcome)

        # Escape in the terminal after a resize cancels the command and changes nothing.
        declare_fixture_server(native_package, project, agent_dir, trusted=True)
        await pilot.click("#refresh")
        await refreshed()
        await select_project_row()
        await pilot.click("#deny")
        await ui.until(lambda: isinstance(app.screen, MCPDecisionScreen), why="the decision dialog")
        modal = app.screen
        terminal = modal.query_one(Terminal)
        await ui.until(lambda: " to apply:" in terminal_text(terminal), why="the package's challenge")
        await ui.resize(105, 38)
        await ui.press("escape")
        await refreshed()
        process = await modal._pty.process()
        await ui.until(lambda: process.master.closed and process.child.retired, why="the cancelled command to be gone")
        assert project_row(screen._inventory).status is ApprovedStatus
        await ui.press("escape")
        assert not isinstance(app.screen, MCPInventoryScreen)
