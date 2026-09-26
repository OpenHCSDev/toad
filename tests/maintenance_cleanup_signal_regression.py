"""Signal-recording only: no processes or namespaces are created or signaled."""

from __future__ import annotations

import os
import signal
import unittest
from unittest.mock import Mock, patch

from maintenance_namespace_probe import retire_exact_pidfd
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
