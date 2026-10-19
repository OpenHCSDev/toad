from pathlib import Path


def format_path(path: Path | str, directory: bool = False) -> str:
    """Format a path, using ~/ syntax as approriate.

    Args:
        path: A path in Path or str form.
        directory: Format path as a directory (append with separator).

    Returns:
        Returns a formatted path string.
    """
    if isinstance(path, str):
        path = Path(path)
    path = path.expanduser().resolve()
    home = Path.home()
    formatted_path = f"~/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)
    if directory and not formatted_path.endswith("/"):
        formatted_path += "/"
    return formatted_path
