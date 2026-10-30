"""Real release controls; only the integration owner executes this selection."""

import shutil
import subprocess
from pathlib import Path

import pytest
from toad.neovim_runtime import Neovim, NeovimUnavailable


@pytest.fixture(scope="module")
def prepared_neovim(tmp_path_factory: pytest.TempPathFactory) -> Neovim:
    requirement = Neovim(tmp_path_factory.mktemp("neovim-release"))
    assert not requirement.root.exists()
    requirement.prepare()
    return requirement


def test_first_preparation_runs_the_declared_release(prepared_neovim: Neovim):
    requirement = prepared_neovim
    output = subprocess.run(
        [str(requirement.executable), "--version"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout
    assert output.splitlines()[0] == f"NVIM v{requirement.version}"
    assert requirement.command() == (
        str(requirement.executable), "--embed", "--clean", "-n"
    )
    assert requirement.executable.is_relative_to(requirement.prefix)


def test_reusable_artifact_is_verified_without_republication(prepared_neovim: Neovim):
    paths = (prepared_neovim.payload, prepared_neovim.executable)
    before = tuple((path.stat().st_ino, path.stat().st_mtime_ns) for path in paths)
    prepared_neovim.prepare()
    assert tuple((path.stat().st_ino, path.stat().st_mtime_ns) for path in paths) == before


def test_corrupt_archive_is_refused_without_replacement(tmp_path: Path):
    requirement = Neovim(tmp_path)
    requirement.root.mkdir(parents=True)
    requirement.payload.write_bytes(b"unfinished or corrupted release")
    with pytest.raises(NeovimUnavailable):
        requirement.prepare()
    assert requirement.payload.read_bytes() == b"unfinished or corrupted release"


def test_corrupt_extracted_executable_is_refused(
    prepared_neovim: Neovim, tmp_path: Path,
):
    requirement = Neovim(tmp_path)
    shutil.copytree(prepared_neovim.root, requirement.root, symlinks=True)
    requirement.executable.write_bytes(b"not the declared Neovim executable")
    with pytest.raises(NeovimUnavailable):
        requirement.prepare()
    assert requirement.executable.read_bytes() == b"not the declared Neovim executable"


def test_same_size_archive_corruption_is_refused(
    prepared_neovim: Neovim, tmp_path: Path,
):
    requirement = Neovim(tmp_path)
    requirement.root.mkdir(parents=True)
    shutil.copyfile(prepared_neovim.payload, requirement.payload)
    with requirement.payload.open("r+b") as stream:
        original = stream.read(1)
        stream.seek(0)
        stream.write(bytes((original[0] ^ 1,)))
    with pytest.raises(NeovimUnavailable):
        requirement.prepare()


def test_runtime_does_not_prepare_or_search_path(tmp_path: Path):
    requirement = Neovim(tmp_path)
    with pytest.raises(NeovimUnavailable):
        requirement.command()
    assert not requirement.root.exists()
