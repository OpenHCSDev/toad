import os
import shlex

from agent_comms.native_arguments import NativeArguments
from importlib.metadata import version
import platform
from string import Template

from toad.app import ToadApp
from toad import paths
from toad import get_version

ABOUT_TEMPLATE = Template(
    """\
# About Toad v${TOAD_VERSION}

© Will McGugan.
                          
Toad is licensed under the terms of the [GNU AFFERO GENERAL PUBLIC LICENSE](https://www.gnu.org/licenses/agpl-3.0.txt).


## Config

config read from `$SETTINGS_PATH`
                                       
```json
$CONFIG                       
```

## Paths

| Name | Path |
| --- | --- |
| App data | `$DATA_PATH` |
| App state | `$STATE_PATH` |
| App logs | `$LOG_PATH` |

## Coordination

Agent Comms uses a shared on-disk wire for persistence. Each Toad conversation
uses its own stdio ACP process and reconnects to its saved wire thread.

| Setting | Effective value |
| --- | --- |
| Wire root (`AGENT_COMMS_ROOT`) | `$COMMS_ROOT` |
| Backend (`AGENT_COMMS_AGENT_BIN`) | `$COMMS_AGENT_BIN` |
| Backend args (`AGENT_COMMS_AGENT_ARGS`) | `$COMMS_AGENT_ARGS` |

                          
## System

| System | Version |
| --- | --- |
| Python | $PYTHON |
| OS | $PLATFORM |
| Terminal | $TERMINAL |

## Dependencies

| Library | Version |
| --- | --- | 
| Toad | $TOAD_VERSION |
| Textual | $TEXTUAL_VERSION |
| Rich | $RICH_VERSION |
                          
## Environment

| Environment variable | Value |                
| --- | --- |
| `SHELL` | $SHELL |
| `TERM` | $TERM |
| `COLORTERM` | $COLORTERM |
| `TERM_PROGRAM` | $TERM_PROGRAM |
| `TERM_PROGRAM_VERSION` | $TERM_PROGRAM_VERSION |
"""
)


def render(app: ToadApp) -> str:
    """Render about markdown.

    Returns:
        Markdown string.
    """

    try:
        config: str | None = app.saved_settings.file_path().read_text()
    except FileNotFoundError:
        # Settings are written on first change; until then there is no file.
        config = None

    service = app.coordination_access.service
    template_data = {
        "COLORTERM": os.environ.get("COLORTERM", ""),
        "COMMS_AGENT_ARGS": shlex.join(NativeArguments.configured().argv),
        "COMMS_AGENT_BIN": NativeArguments.configured_binary(),
        "COMMS_ROOT": str(service.root),
        "CONFIG": config,
        "DATA_PATH": paths.get_data(),
        "LOG_PATH": paths.get_log(),
        "STATE_PATH": paths.get_state(),
        "PLATFORM": platform.platform(),
        "PYTHON": f"{platform.python_implementation()} {platform.python_version()}",
        "RICH_VERSION": version("rich"),
        "SETTINGS_PATH": str(app.saved_settings.file_path()),
        "SHELL": os.environ.get("SHELL", ""),
        "TERM_PROGRAM_VERSION": os.environ.get("TERM_PROGRAM_VERSION", ""),
        "TERM_PROGRAM": os.environ.get("TERM_PROGRAM", ""),
        "TERM": os.environ.get("TERM", ""),
        "TEXTUAL_VERSION": version("textual"),
        "TOAD_VERSION": get_version(),
        "TERMINAL": app.terminal_attention.program,
    }
    return ABOUT_TEMPLATE.safe_substitute(template_data)
