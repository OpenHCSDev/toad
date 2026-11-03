"""Fingerprint a bare interpreter before the test environment has dependencies.

Core's InterpreterBuildProbe qualifies an installed runtime and requires its
packages. This bootstrap key uses only stdlib; it is not an installation proof.
"""

from ctypes.util import dllist
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sys
import sysconfig


def configuration_text(name: str) -> str:
    """Decode the interpreter's foreign build configuration at this boundary."""
    value = sysconfig.get_config_var(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Interpreter does not declare {name}")
    return value


@dataclass(frozen=True)
class ImageRevision:
    device: int
    inode: int
    size: int
    modified: int
    changed: int

    @classmethod
    def of(cls, metadata: os.stat_result) -> "ImageRevision":
        return cls(metadata.st_dev, metadata.st_ino, metadata.st_size,
                   metadata.st_mtime_ns, metadata.st_ctime_ns)


def native_images() -> tuple[Path, ...]:
    images = {Path(sys.executable).resolve(strict=True)}
    for image in dllist():
        # The main image is named separately above. Linux's vDSO has no file;
        # the kernel build is included in the fingerprint instead.
        if not image or image == "linux-vdso.so.1":
            continue
        path = Path(image)
        if not path.is_absolute():
            raise ValueError(f"Loader returned an unresolved native image: {image}")
        images.add(path.resolve(strict=True))
    return tuple(sorted(images))


def fingerprint() -> str:
    digest = hashlib.sha256()
    for value in (
        sys.version,
        str(os.uname()),
        configuration_text("SOABI"),
        str(Path(sysconfig.get_path("stdlib")).resolve(strict=True)),
    ):
        digest.update(value.encode())
        digest.update(b"\0")
    for path in native_images():
        with path.open("rb") as stream:
            before = ImageRevision.of(os.fstat(stream.fileno()))
            content = hashlib.file_digest(stream, "sha256").digest()
            after = ImageRevision.of(os.fstat(stream.fileno()))
            current = ImageRevision.of(path.stat())
        if before != after or after != current:
            raise ValueError(f"Interpreter image changed while reading: {path}")
        digest.update(os.fsencode(path))
        digest.update(b"\0")
        digest.update(content)
    return digest.hexdigest()


if __name__ == "__main__":
    print(fingerprint())
