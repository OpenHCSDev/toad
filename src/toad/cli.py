from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

from agent_comms.field_codec import FieldCodec
from agent_comms.repo import LaunchCheckout
from toad.session_scope import AgentAttached, AgentBinding, NoAgent

if TYPE_CHECKING:
    from toad.app import ToadApp


def persist_terminal_failure(error: Exception) -> None:
    """Keep Textual's terminal failure in the existing diagnostic directory."""
    from toad import paths

    try:
        path = paths.save_traceback(error, "Terminal_crash")
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


async def get_agent_binding(launch_agent: str) -> AgentBinding:
    if not launch_agent:
        return NoAgent()
    requested = launch_agent.lower()

    from toad.agents import read_agents

    agents = await read_agents()

    for agent_data in agents.values():
        if (
            agent_data.short_name.lower() == requested
            or agent_data.identity.lower() == requested
        ):
            return AgentAttached(agent_data)

    known = ", ".join(sorted(
        f"{agent.short_name} ({agent.identity})" if agent.short_name else agent.identity
        for agent in agents.values()
    ))
    raise click.BadParameter(
        f"Unknown agent {launch_agent!r}. Known agents: {known}",
        param_hint="-a / --agent",
    )


class DefaultCommandGroup(click.Group):
    def parse_args(self, ctx, args):
        if "--help" in args or "-h" in args:
            return super().parse_args(ctx, args)
        if "--version" in args or "-v" in args:
            return super().parse_args(ctx, args)
        from agent_comms.active_route import ActiveRoute
        from agent_comms.launch_root import LaunchRoot

        # One selection, as in every Comms process: --comms-root if given, else the published route.
        LaunchRoot.startup(args, ActiveRoute.published_launch)
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
    if version:
        from toad import get_version

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
def run(project_dir: str, agent: str = "1"):
    """Run an installed agent."""

    project = FieldCodec.decode(LaunchCheckout, project_dir)

    import asyncio

    from toad.app import ToadApp

    binding = asyncio.run(get_agent_binding(agent))
    app = ToadApp(
        mode=binding.startup_mode,
        agent_binding=binding,
        project_dir=project,
    )
    run_terminal(app)


@main.command("acp", cls=AcpCommand)
@click.argument("command", metavar="COMMAND")
@click.argument("project_dir", metavar="PATH", default=None)
@click.option(
    "--session",
    "session_id",
    default=None,
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
def acp(
    command: str,
    title: str | None,
    project_dir: str | None,
    session_id: str | None = None,
) -> None:
    """Run an ACP agent from a command."""

    from rich import print
    from toad.agent_schema import AgentDefinition

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
    from toad.app import ToadApp

    app = ToadApp(
        agent_binding=AgentAttached(agent_data),
        project_dir=FieldCodec.decode(LaunchCheckout, project_dir),
        agent_session_id=session_id,
    )
    run_terminal(app)

    print("")
    print("[bold magenta]Thanks for trying out Toad!")
    print("Please head to Discussions to share your experiences (good or bad).")
    print("https://github.com/batrachianai/toad/discussions")


@main.command("settings")
def settings() -> None:
    """Settings information."""
    from toad.preferences import SavedSettings
    print(f"{SavedSettings.file_path()}")


@main.command("replay")
@click.argument("path", metavar="FILE")
def replay(path: str) -> None:
    """Replay interaction from a log file.

    This is a debugging aid. You probably won't need it unless you are building an agent.

    Run it in place of a command line to run an ACP agent:

    toad acp "toad replay toad.log"

    This will replay the agents output, and Toad will update the conversation as it would a real agent.
    """
    import time

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
@click.option("-p", "--port", metavar="PORT", default=8000, type=int)
@click.option(
    "-H",
    "--host",
    metavar="HOST",
    default="127.0.0.1",
    help="Loopback address to listen on (127.0.0.1 or localhost).",
)
@click.argument("toad_args", metavar="[TOAD ARGS]...", nargs=-1, type=click.UNPROCESSED)
def serve(port: int, host: str, toad_args: tuple[str, ...]) -> None:
    """Serve a Toad command line in a web browser.

    Each browser tab runs `toad TOAD ARGS` as its own process, for example
    `toad serve acp agent-comms-acp`.
    """
    import shlex

    from toad.application_lifetime import ApplicationLifetime
    from toad.web_server import ToadWebServer

    command = shlex.join([sys.executable, "-m", "toad", *toad_args])
    server = ToadWebServer(command, host=host, port=port, title="Toad")
    ApplicationLifetime.set_process_title("toad serve")
    server.serve()


@main.command("about")
def about() -> None:
    """Show about information."""

    from toad import about

    print(about.render())


if __name__ == "__main__":
    main()
