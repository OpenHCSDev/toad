"""Run the responsiveness/lifetime pilot suite with bounded subprocess capture."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryFile

import pytest

ROOT = Path(os.environ.get("TOAD_TEST_ROOT", str(Path(__file__).resolve().parents[2])))
PYTHON = os.environ.get("TOAD_TEST_PYTHON", sys.executable)


@pytest.mark.parametrize("name", [
    "comms", "pending_thread_open", "prepared_bars", "work_preparation",
    "transcript_prefetch", "history_scroll_frames", "message_categories",
    "sidebar_pointer_focus", "sidebar_opening_state", "worker_preview",
    "coordination_context", "agent_activity_divider", "existing_thread_link",
    "input_delivery_owner", "native_input_attribution", "goal_objective_edit",
    "current_delivery_owner", "inbound_reconciliation", "committed_history",
    "in_out_filter", "message_filter_supersession", "transcript_teardown",
    "work_preparation_delivery", "serialized_preparation",
    "bar_projection_reuse", "activity_spinners", "session_sort", "sidebar_projection",
    "sidebar_drag_resize", "ui_sidebar_geometry", "tab_scrollbar_top",
    "owner_reader_reuse", "goal_server_poll", "goal_edit_owner",
    "history_mounted_budget", "history_prefetch", "transcript_history",
    "dense_history", "long_message", "user_input_worker",
    "goal_geometry", "goal_resize", "goal_collapse", "goal_separator", "markdown_extent_policy", "first_frame_startup",
    "filter_mount_supersession", "filter_style_scope", "throbber_render_cache",
])
def test_pilot(name):
    # Test-owned persistent services may inherit stdout/stderr. Waiting for
    # pipe EOF can hang after the pilot process has already exited successfully.
    # Preserve bounded process completion and failure output independently.
    with TemporaryFile(mode="w+t") as output:
        result = subprocess.run([PYTHON, str(ROOT / "tests" / f"{name}_pilot.py")],
                                cwd=ROOT, env=os.environ.copy(), stdout=output,
                                stderr=subprocess.STDOUT, text=True, timeout=100)
        output.seek(0)
        assert result.returncode == 0, output.read()
