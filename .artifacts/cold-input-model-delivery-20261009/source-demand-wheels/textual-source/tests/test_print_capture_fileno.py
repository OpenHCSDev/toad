"""Captured output keeps its established file descriptor behavior."""

from unittest.mock import Mock

from textual.app import _PrintCapture


def test_capture_has_no_os_descriptor():
    capture = _PrintCapture(Mock(), stderr=True)
    assert capture.fileno() == -1
