from __future__ import annotations

import asyncio
import importlib.util
import shlex
import sys
import time

import click
import rich
from agent_comms.execution import launch_root
from agent_comms.nominal.field_codec import AcpSessionId, FieldCodec, NoAcpSessionId
from agent_comms.projects.checkouts import Checkout

import __main__
from toad import about, get_version, paths
from toad.client.agent_schema import AgentDefinition
from toad.app import ToadApp
from toad.application_lifetime import TerminalApplicationLifetime
from toad.client.connection import CoreConnection
from toad.client.local_connection import ClientLaunch
from toad.launch_binding import AgentAttached, AgentBinding, LaunchAgentRefused
from toad.preferences import SavedSettings
from toad.web_server import (
    LocalBrowserAuthentication,
    LocalBrowserEndpoint,
    TailnetBrowserAuthentication,
    ToadWebServer,
)


def persist_terminal_failure(error: Exception) -> None:
    """Keep Textual's terminal failure in the existing diagnostic directory."""

    try:
        path = paths.save_error(error, "Terminal_crash")
    except OSError as log_error:
        click.echo(f"Unable to save terminal traceback: {log_error}", err=True)
    else:
        click.echo(f"Terminal traceback saved: {path}", err=True)


def run_terminal(app: ToadApp) -> None:
    """Own both escaping and Textual-retained failures at the CLI boundary."""
    try:
        app.run()
    except Exception as error:
        persist_terminal_failure(error)
        raise
    finally:
        # The failure that ended the app is saved even when closing the app
        # then raised its own error, or was interrupted.
        if app._exception is not None:
            persist_terminal_failure(app._exception)
    if app._exception is not None:
        raise SystemExit(app.return_code or 1)
    app.return_value.finish()


async def get_agent_binding(connection: CoreConnection, launch_agent: str) -> AgentBinding:
    """The launch's agent, chosen by the same owner Qt's launch asks: its connection."""
    try:
        return await AgentBinding.launched(launch_agent, connection.agent_processes)
    except LaunchAgentRefused as error:
        raise click.BadParameter(str(error), param_hint="-a / --agent") from error


class DefaultCommandGroup(click.Group):
    def parse_args(self, ctx, args):
        if "--help" in args or "-h" in args:
            return super().parse_args(ctx, args)
        if "--version" in args or "-v" in args:
            return super().parse_args(ctx, args)

        # The launch's connection and the conversation it opens; apps receive this captured value.
        ctx.obj = ClientLaunch.startup(args)
        # Check if first arg is a known subcommand
        if not args or args[0] not in self.commands:
            # If not a subcommand, prepend the default command name
            args.insert(0, "run")
        return super().parse_args(ctx, args)

    def format_usage(self, ctx, formatter):
        formatter.write_usage(ctx.command_path, "[OPTIONS] PATH OR COMMAND [ARGS]...")


class AcpCommand(click.Command):
    """Decode the two raw project spellings into Click's original value slot."""

    def parse_args(self, ctx, args):
        remaining = super().parse_args(ctx, args)
        project_option = ctx.params.pop("project_option")
        if project_option is not None:
            ctx.params["project_dir"] = project_option
            ctx.set_parameter_source(
                "project_dir", ctx.get_parameter_source("project_option")
            )
        return remaining


@click.group(cls=DefaultCommandGroup, invoke_without_command=True)
@click.option("-v", "--version", is_flag=True, help="Show version and exit.")
@click.pass_context
def main(ctx, version):
    """🐸 Toad — AI for your terminal."""
    launch_root.started()
    # Toad's entry is its package __main__, whichever launcher ran it: say so, as `python -m
    # toad` does. A console script leaves __main__ without a spec, so every spawned helper
    # (render workers, the observation service) re-runs the script and imports the whole app
    # before its own work; a `.__main__` spec is the one spawn skips (multiprocessing/spawn.py).
    __main__.__spec__ = importlib.util.find_spec(".__main__", __package__)
    if version:

        click.echo(get_version())
        ctx.exit()
    # If no command and no version flag, let the default command handling proceed
    if ctx.invoked_subcommand is None and not version:
        pass


# @click.group(invoke_without_command=True)
# @click.pass_context
@main.command("run")
@click.argument("project_dir", metavar="PATH", required=True)
@click.option("-a", "--agent", metavar="AGENT", default="")
@click.pass_obj
def run(launch: ClientLaunch, project_dir: str, agent: str = "1"):
    """Run an installed agent. `--open NAME` (a thread, or #channel) opens that conversation
    once the saved tabs are back."""

    project = FieldCodec.decode(Checkout, project_dir).resolved(strict=True)



    binding = asyncio.run(get_agent_binding(launch.connection, agent))
    app = ToadApp(
        agent_binding=binding,
        project_dir=project,
        connection=launch.connection,
        opening=launch.opening,
    )
    run_terminal(app)


@main.command("acp", cls=AcpCommand)
@click.argument("command", metavar="COMMAND")
@click.argument("project_dir", metavar="PATH", default=None)
@click.option(
    "--session",
    "session_id",
    default=None,
    callback=lambda _context, _option, value: FieldCodec.decode(
        AcpSessionId | NoAcpSessionId, value
    ),
    help="Resume an existing ACP session instead of creating a new one.",
)
@click.option(
    "-t",
    "--title",
    metavar="TITLE",
    help="Optional title to display in the status bar",
    default=None,
)
@click.option("-d", "--project-dir", "project_option", metavar="PATH", default=None)
@click.pass_obj
def acp(
    launch: ClientLaunch,
    command: str,
    title: str | None,
    project_dir: str | None,
    session_id: AcpSessionId | NoAcpSessionId = NoAcpSessionId(),
) -> None:
    """Run an ACP agent from a command."""


    command_name = command.split(" ", 1)[0].lower()
    identity = f"{command_name}.custom.batrachian.ai"

    agent_data = AgentDefinition.decode({
        "identity": identity,
        "name": title or command.partition(" ")[0],
        "short_name": "agent",
        "url": "https://github.com/batrachianai/toad",
        "protocol": "acp",
        "accepts_comms_root": command_name == "agent-comms-acp",
        "type": "coding",
        "author_name": "Will McGugan",
        "author_url": "https://willmcgugan.github.io/",
        "publisher_name": "Will McGugan",
        "publisher_url": "https://willmcgugan.github.io/",
        "description": "Agent launched from CLI",
        "tags": [],
        "help": "",
        "run_command": {"*": command},
        "actions": {},
    })

    app = ToadApp(
        agent_binding=AgentAttached(agent_data),
        project_dir=FieldCodec.decode(Checkout, project_dir).resolved(strict=True),
        connection=launch.connection,
        agent_session_id=session_id,
        opening=launch.opening,
    )
    run_terminal(app)

    rich.print("")
    rich.print("[bold magenta]Thanks for trying out Toad!")
    rich.print("Please head to Discussions to share your experiences (good or bad).")
    rich.print("https://github.com/batrachianai/toad/discussions")


@main.command("settings")
def settings() -> None:
    """Settings information."""
    print(f"{SavedSettings.path()}")


@main.command("replay")
@click.argument("path", metavar="FILE")
def replay(path: str) -> None:
    """Replay interaction from a log file.

    This is a debugging aid. You probably won't need it unless you are building an agent.

    Run it in place of a command line to run an ACP agent:

    toad acp "toad replay toad.log"

    This will replay the agents output, and Toad will update the conversation as it would a real agent.
    """

    stdout = sys.stdout.buffer
    with open(path, "rb") as replay_file:
        for line in replay_file.readlines():
            sender, space, json_line = line.partition(b" ")
            if sender == b"[agent]":
                stdout.write(json_line.strip() + b"\n")
            time.sleep(0.01)
            stdout.write(line)
            stdout.flush()


@main.command(
    "serve",
    context_settings={"allow_interspersed_args": False},
)
@click.option("-p", "--port", metavar="PORT", default=8000, type=click.IntRange(1, 65535))
@click.option(
    "-H",
    "--host",
    metavar="HOST",
    default="127.0.0.1",
    help="Loopback address to listen on (127.0.0.1 or localhost).",
)
@click.argument("toad_args", metavar="[TOAD ARGS]...", nargs=-1, type=click.UNPROCESSED)
def serve(port: int, host: str, toad_args: tuple[str, ...]) -> None:
    """Serve a Toad command line in a web browser on this machine.

    Each browser tab runs `toad TOAD ARGS` as its own process, for example
    `toad serve acp agent-comms-acp`.
    """

    ToadWebServer.run_toad(
        LocalBrowserAuthentication(LocalBrowserEndpoint(host, port)), toad_args
    )


@main.command(
    "serve-tailnet",
    context_settings={"allow_interspersed_args": False},
)
@click.argument("https_port", metavar="PORT", type=click.IntRange(1, 65535))
@click.argument("toad_args", metavar="[TOAD ARGS]...", nargs=-1, type=click.UNPROCESSED)
def serve_tailnet(https_port: int, toad_args: tuple[str, ...]) -> None:
    """Serve a Toad command line to this machine's tailnet owner only.

    Listens on an owner-only unix socket for `tailscale serve --https=PORT`, which
    supplies each caller's tailnet login.
    """

    ToadWebServer.run_toad(TailnetBrowserAuthentication.from_status(https_port), toad_args)


@main.command("about")
@click.pass_obj
def show_about(launch: ClientLaunch) -> None:
    """Show about information."""


    print(about.render(launch.connection.location))


if __name__ == "__main__":
    main()
