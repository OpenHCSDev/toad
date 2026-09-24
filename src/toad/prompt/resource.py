from dataclasses import dataclass
import mimetypes
from pathlib import Path

from agent_comms.image_inputs import MAX_IMAGE_BYTES


@dataclass
class Resource:
    root: Path
    path: Path
    mime_type: str
    text: str | None
    data: bytes | None


class ResourceError(Exception):
    """An error occurred reading a resource."""


class ResourceNotRelative(ResourceError):
    """Attempted to read a resource, not in the project directory."""


class ResourceReadError(ResourceError):
    """Failed to read the resource."""


def load_resource(root: Path, path: Path, *, attachment_root: Path | None = None) -> Resource:
    """Load a resource from the project directory.

    Args:
        root: The project root.
        path: Relative path within project.

    Returns:
        A resource.
    """
    root = root.resolve()
    resource_path = (root / path).resolve()

    if not resource_path.is_relative_to(root) and not (
        attachment_root is not None and resource_path.is_relative_to(attachment_root.resolve())
    ):
        raise ResourceNotRelative("Resource path is not relative to project root.")

    mime_type, encoding = mimetypes.guess_file_type(resource_path)
    if mime_type is None:
        mime_type = "application/octet-stream"

    data: bytes | None
    text: str | None

    try:
        if mime_type.startswith("image/"):
            with resource_path.open("rb") as source:
                data = source.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                raise ResourceReadError("Image exceeds the 4 MiB attachment limit.")
            text = None
        elif encoding is not None:
            data = resource_path.read_bytes()
            text = None
        else:
            data = None
            text = resource_path.read_text(encoding, errors="replace")
    except FileNotFoundError:
        raise ResourceReadError(f"File not found {str(path)!r}")
    except Exception as error:
        raise ResourceReadError(f"Failed to read {str(path)!r}; {error}")

    resource = Resource(
        root,
        resource_path,
        mime_type=mime_type,
        text=text,
        data=data,
    )
    return resource
