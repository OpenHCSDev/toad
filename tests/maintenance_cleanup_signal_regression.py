"""Signal-recording only: no processes or namespaces are created or signaled."""

from __future__ import annotations

import os
import signal
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from maintenance_namespace_probe import adopt_escaped_pidfd, retire_exact_pidfd
from maintenance_stuck_spawn_probe import retire_owned_fixture_process


class CleanupIdentityTests(unittest.TestCase):
    def test_exited_pidfd_does_not_signal_reusable_numeric_pid(self) -> None:
        with patch("maintenance_namespace_probe.select.select", return_value=([41], [], [])), patch.object(
            signal, "pidfd_send_signal"
        ) as send, patch.object(os, "kill", side_effect=AssertionError("raw PID signal")):
            retire_exact_pidfd(41)
            send.assert_not_called()

    def test_live_pidfd_is_the_only_signal_target(self) -> None:
        with patch("maintenance_namespace_probe.select.select", return_value=([], [], [])), patch.object(
            signal, "pidfd_send_signal"
        ) as send, patch.object(os, "kill", side_effect=AssertionError("raw PID signal")):
            retire_exact_pidfd(42)
            send.assert_called_once_with(42, signal.SIGKILL)

    def test_recycled_parent_after_candidate_open_never_arms_signal(self) -> None:
        with patch("maintenance_namespace_probe.pidfd_exited", side_effect=[False, True]), patch.object(
            os, "pidfd_open", return_value=52
        ), patch.object(os, "close") as close, patch.object(
            signal, "pidfd_send_signal", side_effect=AssertionError("unvalidated signal")
        ):
            with self.assertRaisesRegex(RuntimeError, "PID1 exited during"):
                adopt_escaped_pidfd(11, 41, 51, 12)
            close.assert_called_once_with(52)

    def test_wrong_namespace_candidate_never_arms_signal(self) -> None:
        with patch("maintenance_namespace_probe.pidfd_exited", side_effect=[False, False]), patch.object(
            os, "pidfd_open", return_value=52
        ), patch.object(os, "stat", return_value=SimpleNamespace(st_ino=998)), patch.object(
            os, "fstat", return_value=SimpleNamespace(st_ino=999)
        ), patch.object(os, "close") as close, patch.object(
            signal, "pidfd_send_signal", side_effect=AssertionError("unvalidated signal")
        ):
            with self.assertRaisesRegex(RuntimeError, "pinned PID namespace"):
                adopt_escaped_pidfd(11, 41, 51, 12)
            close.assert_called_once_with(52)

    def test_post_validation_pid1_exit_rejects_candidate(self) -> None:
        with patch("maintenance_namespace_probe.pidfd_exited", side_effect=[False, False, True]), patch.object(
            os, "pidfd_open", return_value=52
        ), patch.object(os, "stat", return_value=SimpleNamespace(st_ino=999)), patch.object(
            os, "fstat", return_value=SimpleNamespace(st_ino=999)
        ), patch("maintenance_namespace_probe.children_of", return_value=[12]), patch.object(
            os, "close"
        ) as close, patch.object(signal, "pidfd_send_signal", side_effect=AssertionError("unvalidated signal")):
            with self.assertRaisesRegex(RuntimeError, "exited during validation"):
                adopt_escaped_pidfd(11, 41, 51, 12)
            close.assert_called_once_with(52)

    def test_stuck_fixture_kills_only_tracked_unreaped_process(self) -> None:
        process = Mock()
        process.poll.return_value = None
        process.communicate.return_value = (b"", b"")
        with patch.object(os, "killpg", side_effect=AssertionError("raw process-group signal")):
            retire_owned_fixture_process(process)
        process.kill.assert_called_once_with()
        process.communicate.assert_called_once_with(timeout=5)


if __name__ == "__main__":
    unittest.main()
