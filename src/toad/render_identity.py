"""Content identity for persistent renderer code, including editable dependencies.

Capture this off the UI loop before connecting. Distribution versions alone are
insufficient for editable Toad/Textual installations. The service independently
captures the same identity before it advertises readiness.
"""

from dataclasses import dataclass
from hashlib import sha256
from importlib.machinery import EXTENSION_SUFFIXES
from importlib.util import find_spec
from pathlib import Path
import sys

from toad.render_service import RenderServiceConfig


# Packages used by the closed render-task set, its result types and wire codec.
_RENDER_PACKAGES = (
    "toad", "agent_comms", "textual", "textual_diff_view", "rich", "pygments",
    "markdown_it", "mdurl", "mdit_py_plugins", "linkify_it",
    "textual_speedups", "zmqruntime", "zmq",
)
_SOURCE_SUFFIXES = (".py", ".pyi", ".json", ".tcss", *EXTENSION_SUFFIXES)


@dataclass(frozen=True)
class RenderCodePackage:
    name: str
    location: Path

    def fingerprint(self) -> str:
        """Hash names and contents; ignore bytecode and generated cache files."""
        root = self.location.resolve(strict=True)
        digest = sha256()
        digest.update(f"{self.name}\0{root}\0".encode())
        paths = sorted(root.rglob("*")) if root.is_dir() else [root]
        for path in paths:
            if (not path.is_file() or "__pycache__" in path.parts
                    or not path.name.endswith(_SOURCE_SUFFIXES)):
                continue
            name = str(path.relative_to(root)) if path != root else path.name
            digest.update(name.encode() + b"\0")
            digest.update(sha256(path.read_bytes()).digest())
        return digest.hexdigest()


@dataclass(frozen=True)
class RendererBuild:
    interpreter: str
    packages: tuple[RenderCodePackage, ...]
    config: RenderServiceConfig

    @property
    def version(self) -> str:
        digest = sha256(b"toad-render-protocol-1\0")
        digest.update(self.interpreter.encode() + b"\0")
        config = self.config
        digest.update(f"{config.max_workers}:{config.max_pending}:{config.client_lease_seconds:g}\0".encode())
        for package in self.packages:
            digest.update(package.fingerprint().encode() + b"\0")
        return digest.hexdigest()

    @classmethod
    def current(cls, config: RenderServiceConfig) -> "RendererBuild":
        packages: list[RenderCodePackage] = []
        for name in _RENDER_PACKAGES:
            spec = find_spec(name)
            if spec is None or spec.origin is None:
                raise RuntimeError(f"Renderer dependency has no source identity: {name}")
            origin = Path(spec.origin)
            location = origin.parent if spec.submodule_search_locations is not None else origin
            packages.append(RenderCodePackage(name, location))
        interpreter = f"{Path(sys.executable).resolve()}:{sys.prefix}:{sys.version}:{sys.implementation.cache_tag}"
        return cls(interpreter, tuple(packages), config)
