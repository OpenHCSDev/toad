"""The pinned Neovim artifact, prepared before publication rather than on input."""

from __future__ import annotations

import errno
import hashlib
import os
import platform
import stat
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path, PurePosixPath
from shutil import copyfileobj
from tempfile import TemporaryDirectory
from typing import ClassVar
from urllib.request import urlopen

from agent_comms.installer.native_build_inputs import Executable
from agent_comms.installer.runtime_preparation import RuntimePreparation
from agent_comms.nominal.declared_family import DeclaredFamily

from toad.platform import AndroidPlatform, LinuxPlatform, MacPlatform, Platform, host


class NeovimUnavailable(OSError):
    """The declared artifact is missing, unsupported or fails verification."""


class Architecture(DeclaredFamily, affix="Architecture"):
    """Decode external machine spellings once into release architecture identity."""

    tag: ClassVar[str]
    aliases: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def decode(cls, machine: str) -> type[Architecture]:
        spelling = machine.casefold()
        for member in cls.members_with(Architecture):
            if spelling in (member.tag, *member.aliases):
                return member
        raise NeovimUnavailable(f"No declared Neovim architecture for {machine!r}")


class X64Architecture(Architecture):
    tag = "x86_64"
    aliases = ("amd64",)


class PackageArchitecture(Architecture):
    """The package manager selects the native machine binary, not a release archive."""

    tag = "native"


class Arm64Architecture(Architecture):
    tag = "arm64"
    aliases = ("aarch64",)


@dataclass(frozen=True)
class ReleaseArchive:
    """Trusted release metadata, not a checksum fetched beside an untrusted download."""

    platform: type[Platform]
    architecture: type[Architecture]
    size: int
    sha256: bytes

    @property
    def name(self) -> str:
        return f"{Neovim.program}-{self.platform.key}-{self.architecture.tag}.tar.gz"

    @property
    def directory(self) -> str:
        return self.name.removesuffix(".tar.gz")

    def verify(self, path: Path) -> None:
        if path.stat().st_size != self.size:
            raise NeovimUnavailable(f"Neovim archive size mismatch: {path}")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").digest()
        if actual != self.sha256:
            raise NeovimUnavailable(f"Neovim archive SHA-256 mismatch: {path}")

    kept: ClassVar[Path] = Path.home() / ".cache/toad/neovim-archives"
    """Every verified release archive, kept under its own SHA-256 for later runtimes. An
    archive's identity is its content, but its only copy lived inside one runtime's prefix,
    so every fresh prefix re-fetched the same pinned 11 MB from GitHub and two installs
    failed on HTTP 504 (2026-11-08) with verified byte-identical copies already on the disk."""

    @property
    def held(self) -> Path:
        """Where these exact bytes live once this disk has them."""
        return self.kept / self.sha256.hex()

    def kept_copy(self) -> Path | None:
        """A verified copy of exactly these bytes on this disk, or None.

        The file's name is its content, so one that fails verification under that name is
        not this archive: it is discarded and fetched again, rather than failing every
        future install from one bad write.
        """
        if not self.held.is_file():
            return None
        try:
            self.verify(self.held)
        except NeovimUnavailable:
            self.held.unlink(missing_ok=True)
            return None
        return self.held

    def acquire(self, url: str, destination: Path) -> None:
        """These bytes: from this disk when it already holds them, from the network once."""
        kept = self.kept_copy()
        if kept is None:
            self.download(url, destination)
            self.keep(destination)
            return
        with kept.open("rb") as source, destination.open("xb") as output:
            copyfileobj(source, output)
        self.verify(destination)

    def keep(self, source: Path) -> None:
        """Publish a verified download for every later runtime, visible only once complete."""
        self.kept.mkdir(mode=0o700, parents=True, exist_ok=True)
        staged = self.kept.joinpath(f".{self.sha256.hex()}.{os.getpid()}")
        with source.open("rb") as reading, staged.open("wb") as output:
            copyfileobj(reading, output)
        os.replace(staged, self.held)

    def download(self, url: str, destination: Path) -> None:
        remaining = self.size
        with urlopen(url, timeout=30) as response, destination.open("xb") as output:
            while block := response.read(min(1024 * 1024, remaining + 1)):
                remaining -= len(block)
                if remaining < 0:
                    raise NeovimUnavailable(f"Neovim archive exceeds declared size: {url}")
                output.write(block)
        self.verify(destination)


@dataclass(frozen=True)
class Neovim(RuntimePreparation, Executable):
    """The platform owns preparation and launch; the default is the verified release."""

    implementations: ClassVar[dict[type[Platform], type[Neovim]]] = {}

    def __init_subclass__(cls, *, system: type[Platform], **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if system in cls.implementations:
            raise TypeError(f"Neovim already has an implementation for {system.system}")
        cls.implementations[system] = cls

    def __new__(cls, prefix: Path = Path(sys.prefix), system: type[Platform] = host,
                architecture: type[Architecture] | None = None):
        return object.__new__(cls.implementations.get(system, cls))

    program: ClassVar[str] = "nvim"
    version: ClassVar[str] = "0.12.4"
    executable_mode: ClassVar[int] = 0o755
    # Official neovim/neovim v0.12.4 release metadata, retained by P928.
    # These are external artifact records, not a roster of editing-mode members.
    archives: ClassVar[tuple[ReleaseArchive, ...]] = (
        ReleaseArchive(LinuxPlatform, Arm64Architecture, 11353219, bytes.fromhex(
            "ceb7e88c6b681f0515d135dcdfad54f5eb4373b25ce6172197cd9a69c758063f")),
        ReleaseArchive(LinuxPlatform, X64Architecture, 11404178, bytes.fromhex(
            "012bf3fcac5ade43914df3f174668bf64d05e049a4f032a388c027b1ebd78628")),
        ReleaseArchive(MacPlatform, Arm64Architecture, 9630250, bytes.fromhex(
            "51ab83afa66d663627c2ab1be43209b0f4e81360d4598b53efaa4d8195f24c89")),
        ReleaseArchive(MacPlatform, X64Architecture, 9896697, bytes.fromhex(
            "03fe16f8dd9f1e9eaf52d5e294913a39917b9e2faea30d7fb0fb385fbd36fe59")),
    )

    prefix: Path = Path(sys.prefix)
    system: type[Platform] = host
    architecture: type[Architecture] = field(
        default_factory=lambda: Architecture.decode(platform.machine())
    )

    @cached_property
    def archive(self) -> ReleaseArchive:
        for archive in self.archives:
            if (archive.platform, archive.architecture) == (self.system, self.architecture):
                return archive
        raise NeovimUnavailable(
            f"Neovim {self.version} has no declared asset for "
            f"{self.system.system}/{self.architecture.tag}"
        )

    @property
    def root(self) -> Path:
        return self.prefix / "share" / "toad" / "neovim" / self.version / self.archive.directory

    @property
    def payload(self) -> Path:
        return self.root / self.archive.name

    @property
    def executable(self) -> Path:
        path = self.root / self.archive.directory / "bin" / self.program
        try:
            info = path.lstat()
        except FileNotFoundError as error:
            raise NeovimUnavailable(
                f"Neovim {self.version} is not prepared at {path}; "
                "run target-runtime preparation before selecting the native editor"
            ) from error
        if (not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != self.executable_mode):
            raise NeovimUnavailable(f"Neovim executable has unsafe type or permissions: {path}")
        return path

    def command(self) -> tuple[str, ...]:
        """No PATH discovery, download or alternate editor on the runtime path."""
        return str(self.executable), "--embed", "--clean", "-n"

    def verify(self) -> None:
        """The trusted archive supplies every extracted file and link's expected answer."""
        self.archive.verify(self.payload)
        expected_paths = {self.payload}
        with tarfile.open(self.payload, "r:gz") as archive:
            for member in archive:
                parts = PurePosixPath(member.name).parts
                if not parts or parts[0] != self.archive.directory:
                    raise NeovimUnavailable(f"Unexpected Neovim archive root: {member.name}")
                tarfile.data_filter(member, str(self.root))
                relative = Path(member.name)
                path = self.root / relative
                expected_paths.add(path)
                expected_paths.update(
                    self.root / parent for parent in relative.parents if parent != Path(".")
                )
                if member.issym():
                    if not path.is_symlink() or os.readlink(path) != member.linkname:
                        raise NeovimUnavailable(f"Neovim link differs from archive: {path}")
                elif member.isfile() or member.islnk():
                    if path.is_symlink() or not path.is_file():
                        raise NeovimUnavailable(f"Neovim file missing or replaced: {path}")
                    expected = archive.extractfile(member)
                    if expected is None:
                        raise NeovimUnavailable(f"Neovim archive file has no payload: {member.name}")
                    with expected, path.open("rb") as actual:
                        if (hashlib.file_digest(expected, "sha256").digest()
                                != hashlib.file_digest(actual, "sha256").digest()):
                            raise NeovimUnavailable(f"Neovim file differs from archive: {path}")
                elif member.isdir():
                    if path.is_symlink() or not path.is_dir():
                        raise NeovimUnavailable(f"Neovim directory missing or replaced: {path}")
                else:
                    raise NeovimUnavailable(f"Unsupported Neovim archive member: {member.name}")
        if set(self.root.rglob("*")) != expected_paths:
            raise NeovimUnavailable(f"Neovim tree contains undeclared or missing paths: {self.root}")
        self.executable

    def prepare(self) -> None:
        """Filesystem admission is separate from use; only a completed tree is published."""
        if self.root.exists():
            self.verify()
            return
        self.root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".neovim-", dir=self.root.parent) as temporary:
            staged = Neovim(Path(temporary), self.system, self.architecture)
            staged.root.mkdir(mode=0o700, parents=True)
            url = (f"https://github.com/neovim/neovim/releases/download/"
                   f"v{self.version}/{self.archive.name}")
            self.archive.acquire(url, staged.payload)
            with tarfile.open(staged.payload, "r:gz") as archive:
                archive.extractall(staged.root, filter="data")
            staged.executable.chmod(self.executable_mode)
            staged.verify()
            try:
                os.rename(staged.root, self.root)
            except OSError as error:
                if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    raise
                # A concurrent preparer may publish the same complete artifact first.
                self.verify()


@dataclass(frozen=True)
class TermuxNeovim(Neovim, system=AndroidPlatform):
    """Termux's package owns the Android binary and its runtime files."""

    prefix: Path = Path(sys.base_prefix)
    system: type[Platform] = AndroidPlatform
    architecture: type[Architecture] = PackageArchitecture

    @property
    def executable(self) -> Path:
        path = self.prefix / "bin" / self.program
        if not path.is_file() or not os.access(path, os.X_OK):
            raise NeovimUnavailable(f"Termux Neovim is not installed at {path}; run pkg install neovim")
        return path

    @cached_property
    def version(self) -> str:
        output = subprocess.run((str(self.executable), "--version"), check=True,
                                capture_output=True, text=True, timeout=30).stdout
        return output.splitlines()[0].removeprefix("NVIM v")

    def verify(self) -> None:
        self.executable

    def prepare(self) -> None:
        self.verify()


if __name__ == "__main__":
    requirement = Neovim()
    requirement.prepare()
    print(requirement.executable)
