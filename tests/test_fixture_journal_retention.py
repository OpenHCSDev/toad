"""Offline authored storage contracts; no App, source journal or HDD operation."""

import ast
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


# Compile the exact stdlib-only retention declarations from their original
# shared fixture. Importing that whole App helper would acquire native resources
# that are unrelated to these offline filesystem contracts.
SOURCE = Path(__file__).with_name("runtime_fixture.py")
NAMES = {"retain_fixture_journals", "_fixture_copy_metadata", "_fixture_source_identity",
         "_require_private_fixture_directory", "_remove_owned_fixture_copy",
         "_sync_fixture_directory"}
DECLARATIONS = [node for node in ast.parse(SOURCE.read_text()).body
                if isinstance(node, ast.FunctionDef) and node.name in NAMES]
assert {node.name for node in DECLARATIONS} == NAMES
OWNER = dict(ExitStack=ExitStack, Path=Path, hashlib=hashlib, json=json, os=os,
             shutil=shutil, stat=stat, subprocess=subprocess, sys=sys)
exec(compile(ast.Module(body=DECLARATIONS, type_ignores=[]), str(SOURCE), "exec"), OWNER)


class JournalRetention(unittest.TestCase):
    def setUp(self):
        scratch = Path(os.environ["RETENTION_TEST_ROOT"])
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch, prefix="authored-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / "fixture"
        self.source = self.stage / "native-forks" / "sessions" / "child.jsonl"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'{"authored_storage_control":true}\n')
        self.source.chmod(0o640)
        os.utime(self.source, ns=(1_000_000_000_000_000_123, 1_000_000_000_000_000_456))
        self.before = OWNER["_fixture_source_identity"](self.source.lstat())
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.cold = self.root / "authored-mounted-device"
        self.cold.mkdir()
        self.destination = (self.cold / "agent-comms-retained" / "history-sdk-fixture"
                            / self.source.relative_to(self.source.anchor))
        self.mounted = True
        self.gaps = []
        self.refs = []
        original_stat, original_lstat, original_fstat = Path.stat, Path.lstat, os.fstat
        original_is_mount, original_is_file = Path.is_mount, Path.is_file
        device = original_stat(self.cold).st_dev + 1

        def device_result(info):
            values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            values["st_dev"] = device
            return SimpleNamespace(**values)

        def authored_stat(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            return device_result(info) if path.is_relative_to(self.cold) else info

        def authored_lstat(path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            return device_result(info) if path.is_relative_to(self.cold) else info

        def authored_fstat(descriptor):
            info = original_fstat(descriptor)
            path = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
            return device_result(info) if path.is_relative_to(self.cold) else info

        def authored_census(command, **kwargs):
            Path(command[-1]).write_text(json.dumps({
                "gaps": self.gaps, "refs": {str(self.source): self.refs},
            }))
            return subprocess.CompletedProcess(command, 0)

        contexts = ExitStack()
        self.addCleanup(contexts.close)
        # Only mount/device/census prerequisites are authored. Copy, SHA,
        # permissions, timestamps, hardlink publication and rename use the real
        # local filesystem; this does not qualify the actual HDD's metadata.
        contexts.enter_context(patch.object(Path, "stat", authored_stat))
        contexts.enter_context(patch.object(Path, "lstat", authored_lstat))
        contexts.enter_context(patch.object(os, "fstat", authored_fstat))
        contexts.enter_context(patch.object(Path, "is_mount", lambda path:
            self.mounted if path == self.cold else original_is_mount(path)))
        contexts.enter_context(patch.object(Path, "is_file", lambda path:
            True if path.name == "borrower-census.py" else original_is_file(path)))
        contexts.enter_context(patch.object(subprocess, "run", authored_census))

    def retain(self):
        receipt = OWNER["retain_fixture_journals"]([self.source], stage=self.stage,
                                                  evidence=self.evidence, cold_mount=self.cold)
        self.assertEqual(receipt, json.loads((self.evidence / "journal-retention.json").read_text()))
        return receipt

    def assert_original(self, expected=None):
        self.assertFalse(self.source.is_symlink())
        self.assertEqual(OWNER["_fixture_source_identity"](self.source.lstat()),
                         self.before if expected is None else expected)
        descriptor = os.open(self.source, os.O_RDONLY | os.O_NOATIME)
        with os.fdopen(descriptor, "rb") as source:
            self.assertEqual(source.read(), b'{"authored_storage_control":true}\n')

    def assert_no_copy(self):
        self.assertFalse(os.path.lexists(self.destination))
        self.assertFalse(os.path.lexists(self.destination.with_name(self.destination.name + ".partial")))
        self.assertFalse(os.path.lexists(self.source.with_name(self.source.name + ".cold-link")))

    def test_verified_copy_preserves_mode_times_and_original_path(self):
        metadata = OWNER["_fixture_copy_metadata"](self.source.lstat())
        receipt = self.retain()
        self.assertNotIn("retained_reason", receipt)
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(self.source.readlink(), self.destination)
        self.assertEqual(OWNER["_fixture_copy_metadata"](self.destination.stat()), metadata)
        record, = receipt["files"]
        self.assertTrue(record["copied_metadata_verified"])
        self.assertTrue(record["private_directories_verified"])
        self.assertTrue(record["original_replaced"])
        self.assertTrue(record["verified_through_original_path"])
        self.assertEqual(record["sha256"], hashlib.sha256(b'{"authored_storage_control":true}\n').hexdigest())
        for directory in self.destination.parents:
            if directory.name == "agent-comms-retained":
                break
            self.assertEqual(stat.S_IMODE(directory.lstat().st_mode), 0o700)
        self.assert_no_unpublished_copy()

    def assert_no_unpublished_copy(self):
        self.assertFalse(self.destination.with_name(self.destination.name + ".partial").exists())
        self.assertFalse(os.path.lexists(self.source.with_name(self.source.name + ".cold-link")))

    def test_unsupported_directory_modes_refuse_before_any_private_copy(self):
        original_mkdir = Path.mkdir
        def discarded_mode(path, *args, **kwargs):
            original_mkdir(path, *args, **kwargs)
            if path.is_relative_to(self.cold):
                path.chmod(0o755)
        with patch.object(Path, "mkdir", discarded_mode), patch.object(shutil, "copyfileobj") as copy:
            receipt = self.retain()
        self.assertIn("private fixture access", receipt["retained_reason"])
        copy.assert_not_called()
        self.assert_original()
        self.assert_no_copy()

    def test_existing_shared_directory_is_never_chmodded(self):
        private_root = self.cold / "agent-comms-retained" / "history-sdk-fixture"
        private_root.mkdir(parents=True, mode=0o755)
        with patch.object(os, "chmod") as chmod, patch.object(shutil, "copyfileobj") as copy:
            receipt = self.retain()
        self.assertIn("private fixture access", receipt["retained_reason"])
        chmod.assert_not_called()
        copy.assert_not_called()
        self.assert_original()

    def test_discarded_file_mode_refuses_and_removes_owned_partial(self):
        with patch.object(os, "fchmod", return_value=None):
            receipt = self.retain()
        self.assertIn("does not preserve fixture metadata", receipt["retained_reason"])
        self.assert_original()
        self.assert_no_copy()

    def test_discarded_timestamp_refuses_and_removes_owned_partial(self):
        with patch.object(os, "utime", return_value=None):
            receipt = self.retain()
        self.assertIn("does not preserve fixture metadata", receipt["retained_reason"])
        self.assert_original()
        self.assert_no_copy()

    def test_existing_destination_is_not_replaced(self):
        self.destination.parent.mkdir(parents=True)
        for directory in self.destination.parents:
            if directory.name == "agent-comms-retained":
                break
            directory.chmod(0o700)
        self.destination.write_bytes(b"other retained owner")
        receipt = self.retain()
        self.assertIn("retained_reason", receipt)
        self.assert_original()
        self.assertEqual(self.destination.read_bytes(), b"other retained owner")

    def test_other_partial_is_not_deleted(self):
        self.destination.parent.mkdir(parents=True)
        for directory in self.destination.parents:
            if directory.name == "agent-comms-retained":
                break
            directory.chmod(0o700)
        partial = self.destination.with_name(self.destination.name + ".partial")
        partial.write_bytes(b"another attempt")
        receipt = self.retain()
        self.assertIn("retained_reason", receipt)
        self.assert_original()
        self.assertEqual(partial.read_bytes(), b"another attempt")

    def test_original_mode_change_before_commit_refuses_without_reverting_it(self):
        original_link = os.link
        expected = None
        def change_source(*args, **kwargs):
            nonlocal expected
            original_link(*args, **kwargs)
            self.source.chmod(0o600)
            expected = OWNER["_fixture_source_identity"](self.source.lstat())
        with patch.object(os, "link", change_source):
            receipt = self.retain()
        self.assertIn("Original fixture journal changed", receipt["retained_reason"])
        self.assert_original(expected)
        self.assert_no_copy()

    def test_private_access_revoked_after_copy_retains_original(self):
        original_link = os.link
        def revoke_directory(*args, **kwargs):
            original_link(*args, **kwargs)
            self.destination.parent.chmod(0o755)
        with patch.object(os, "link", revoke_directory):
            receipt = self.retain()
        self.assertIn("private fixture access", receipt["retained_reason"])
        self.assert_original()
        self.assert_no_copy()

    def test_mount_replaced_before_commit_retains_original(self):
        original_link = os.link
        def revoke_mount(*args, **kwargs):
            original_link(*args, **kwargs)
            self.mounted = False
        with patch.object(os, "link", revoke_mount):
            receipt = self.retain()
        self.assertIn("mount changed", receipt["retained_reason"])
        self.assert_original()
        self.assert_no_copy()

    def test_open_borrower_and_permission_gap_refuse(self):
        for refs, gaps in ((["authored borrower"], []), ([], ["authored gap"])):
            self.refs, self.gaps = refs, gaps
            with patch.object(shutil, "copyfileobj") as copy:
                receipt = self.retain()
            self.assertIn("Borrowers or census", receipt["retained_reason"])
            copy.assert_not_called()
            self.assert_original()
            self.assert_no_copy()


if __name__ == "__main__":
    unittest.main()
