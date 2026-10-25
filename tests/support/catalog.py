"""A private agent catalog entry, added where Toad reads its catalog.

The catalog is package data, so a test cannot add a file to it without writing into the
installation. The entry is decoded from catalog TOML exactly as a shipped one is and joins the
shipped entries at the one read.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import shlex
import sys
import tomllib
from unittest.mock import patch

IDENTITY = "native-fixture"

COMMANDS = {
    "install": ("Install local control", "printf CMD_INSTALL_ORIGINAL; exit 7"),
    "install-acp": ("Install ACP local control", "printf CMD_ADAPTER_OK"),
    "login": ("Login local control", "printf CMD_LOGIN_OK"),
    "owner-custom-script": ("Run arbitrary script", "printf CMD_CUSTOM_OK"),
    "hold": ("Cancel held local command", "printf CMD_HELD; sleep 30"),
    "audit": ("Declaration-only audit", "printf CMD_AUDIT_OK"),
    "bootstrap": ("Sequential local bootstrap", "printf CMD_BOOTSTRAP_MAIN"),
    "input": ("Actual terminal input", 'printf CMD_INPUT_READY; read line; printf CMD_INPUT:%s "$line"'),
}


def catalog_text() -> str:
    """Catalog TOML for an agent that runs Core's ACP server and has local shell commands as actions.

    A wildcard ``install`` action is declared too; this platform's own action must win over it.
    """
    import toad

    definition = {
        "identity": IDENTITY, "name": "A native catalog control", "short_name": "native-control",
        "protocol": "acp", "type": "coding", "author_name": "Private controlled test",
        "accepts_comms_root": True,
        "description": "Local commands only",
        "help": "# Native catalog control\nPrivate controlled command data.",
    }
    text = "".join(f"{key} = {json.dumps(value)}\n" for key, value in definition.items())
    text += '\n[run_command]\n"*" = ' + json.dumps(shlex.join([sys.executable, "-m", "agent_comms.acp"])) + "\n"
    text += '\n[actions."*".install]\ndescription = "Wrong platform"\ncommand = "exit 91"\n'
    for name, (label, command) in COMMANDS.items():
        text += f"\n[actions.{json.dumps(toad.host.key)}.{json.dumps(name)}]\n"
        text += f"description = {json.dumps(label)}\ncommand = {json.dumps(command)}\n"
        if name == "bootstrap":
            text += "bootstrap_uv = true\n"
    return text


def private_definition():
    from toad.agent_schema import AgentDefinition

    return AgentDefinition.decode(tomllib.loads(catalog_text()))


@contextmanager
def private_catalog_entry():
    """While open, Toad's catalog is the shipped one plus the private entry; yields its definition."""
    from toad import agents

    shipped = agents.read_agents
    definition = private_definition()

    async def read_agents():
        return {**await shipped(), definition.identity: definition}

    with patch("toad.agents.read_agents", read_agents), patch("toad.screens.store.read_agents", read_agents):
        yield definition
