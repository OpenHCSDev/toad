"""Real release controls; only the integration owner executes this selection."""

import shutil
import subprocess
from pathlib import Path

import pytest
from toad.neovim_runtime import (
    Neovim, NeovimUnavailable, ReleaseArchive, X64Architecture,
)
from toad.platform import WindowsPlatform


@pytest.mark.parametrize("archive", Neovim.archives)
def test_release_selection_uses_the_declared_pair(archive: ReleaseArchive, tmp_path: Path):
    requirement = Neovim(tmp_path, archive.platform, archive.architecture)
    assert requirement.archive is archive
    assert not requirement.root.exists()


def test_unsupported_pair_refuses_without_preparation(tmp_path: Path):
    requirement = Neovim(tmp_path, WindowsPlatform, X64Architecture)
    with pytest.raises(NeovimUnavailable):
        requirement.command()
    assert not (tmp_path / "share").exists()


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


def test_android_uses_the_native_package_without_an_archive(tmp_path: Path):
    from toad.platform import Platform

    executable = tmp_path / "bin" / "nvim"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    requirement = Neovim(tmp_path, Platform.decode("Android"))
    assert requirement.command() == (str(executable), "--embed", "--clean", "-n")
    requirement.prepare()
    assert not (tmp_path / "share").exists()


def test_android_missing_package_names_its_install_command(tmp_path: Path):
    from toad.platform import Platform

    requirement = Neovim(tmp_path, Platform.decode("Android"))
    with pytest.raises(NeovimUnavailable, match="pkg install neovim"):
        requirement.command()
