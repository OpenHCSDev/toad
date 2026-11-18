import os
import traceback
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from agent_comms.projects.checkouts import Checkout
from typing import Final

from xdg_base_dirs import xdg_config_home, xdg_data_home, xdg_state_home


APP_NAME: Final[str] = "toad"


def path_to_name(path: Path) -> str:
    """Converts a path to a name (suitable as a path component).

    Args:
        path: A path.

    Returns:
        A stringified version of the path.
    """
    name = str(path.resolve()).lstrip("/").replace("/", "-")
    return name


def get_data() -> Path:
    """Return (possibly creating) the application data directory."""
    path = xdg_data_home() / APP_NAME
    with suppress(OSError):
        path.mkdir(0o700, exist_ok=True, parents=True)
    return path


def get_config() -> Path:
    """Return (possibly creating) the application config directory."""
    path = xdg_config_home() / APP_NAME
    with suppress(OSError):
        path.mkdir(0o700, exist_ok=True, parents=True)
    return path


def get_state() -> Path:
    """Return (possibly creating) the application state directory."""
    path = xdg_state_home() / APP_NAME
    with suppress(OSError):
        path.mkdir(0o700, exist_ok=True, parents=True)
    return path


def get_project_data(project_path: Checkout) -> Path:
    """Get a directory for per-project data.

    Args:
        project_path: Path of project.

    """
    project_data_path = get_data() / path_to_name(project_path.path)
    with suppress(OSError):
        project_data_path.mkdir(0o700, exist_ok=True, parents=True)
    return project_data_path


def generate_datetime_filename(prefix: str, suffix: str) -> str:
    """A file name holding the current date and time after ``prefix``, made safe for every
    filesystem; ``suffix`` includes the extension."""
    file_name_stem = f"{prefix} {datetime.now().isoformat()}"
    for reserved in ' <>:"/\\|?*.':
        file_name_stem = file_name_stem.replace(reserved, "_")
    return file_name_stem + suffix


def save_error(error: BaseException | str, prefix: str) -> Path:
    """Persist an error under a timestamped name in logs/errors."""
    return _save_report(error, prefix, get_errors())


def save_warning(text: str, prefix: str) -> Path:
    """Persist a warning the reader was shown under a timestamped name in logs/warnings:
    a warning is not a failure (logs/errors stays the failures), but its notice puts itself
    away, so it is kept to be read back."""
    return _save_report(text, prefix, get_warnings())


def _save_report(error: BaseException | str, prefix: str, directory: Path) -> Path:
    """An exception's traceback and chained causes, or text with the stack that reported it."""
    if isinstance(error, BaseException):
        report = traceback.format_exception(error)
    else:
        report = [f"{error}\n\nReported from:\n", *traceback.format_stack()[:-2]]
    path = directory / generate_datetime_filename(prefix, ".txt")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.writelines(report)
    return path


def get_warnings() -> Path:
    """The directory holding the warnings the reader was shown."""
    path = get_log() / "warnings"
    path.mkdir(0o700, exist_ok=True)
    return path


def get_errors() -> Path:
    """The directory holding saved exception tracebacks, apart from agent logs."""
    path = get_log() / "errors"
    path.mkdir(0o700, exist_ok=True)
    return path


def get_log() -> Path:
    """Get a directory for logs.

    Returns:
        Path to log directory.

    """
    path = get_state() / "logs"
    with suppress(OSError):
        path.mkdir(0o700, exist_ok=True, parents=True)
    return path
