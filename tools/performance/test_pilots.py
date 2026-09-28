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
    "channel_roster_retention",
    "shared_channels",
    "session_details",
    "sidebar_drag_resize", "ui_sidebar_geometry", "tab_scrollbar_top",
    "owner_reader_reuse", "goal_server_poll", "goal_edit_owner",
    "history_mounted_budget", "history_prefetch", "transcript_history",
    "dense_history", "long_message", "user_input_worker",
    "goal_geometry", "goal_resize", "goal_collapse", "goal_separator", "markdown_extent_policy", "first_frame_startup",
    "filter_mount_supersession", "filter_style_scope", "throbber_render_cache",
    "viewport_body_lifetime", "acp_process_validation", "acp_sdk_boundary",
    "async_tab_activation",
    "projected_history_budget",
    "in_out_underfill", "off_tail_checkpoint", "tail_anchor_policy", "history_anchor_geometry",
    # Landing coverage for the current-main route, queue, private-history and
    # MCP contracts. All use disposable/provider-free fixtures.
    "default_route", "default_route_admission", "default_route_cancel",
    "default_route_private_user", "default_route_prompt_selection", "default_route_retirement",
    "input_failure", "maintenance_agent_root_binding", "maintenance_cancel_process_group",
    "maintenance_ingress", "mcp_decision_pty", "mcp_inventory", "mcp_live_status",
    "mcp_permission_boundary", "mcp_permission_ui", "private_native_cursor",
    "private_native_cursor_request", "queue_manage", "queue_view", "queue_view_backend",
    "queue_view_bounds", "queue_view_request",
    # Preserve current-main nominal transcript, goal, read-proof and historical
    # view contracts when integrating the framework performance checkpoint.
    "historical_views", "channel_partial_paint", "channel_display_basis",
    "channel_views", "native_message_parts", "tool_diff", "transcript_process",
    "right_comms_integration", "thread_unread_start", "goal_set_owner",
    "goal_pause_owner", "recovery_view_boundaries", "channel_any_mode_ui",
    "dm_rebind_paint",
    "message_notifications", "observed_thread_activity",
    "channel_visibility_observation", "channel_history_reader",
])
def test_pilot(name):
    # Test-owned persistent services may inherit stdout/stderr. Waiting for
    # pipe EOF can hang after the pilot process has already exited successfully.
    # Preserve bounded process completion and failure output independently.
    with TemporaryFile(mode="w+t") as output:
        try:
            result = subprocess.run([PYTHON, str(ROOT / "tests" / f"{name}_pilot.py")],
                                    cwd=ROOT, env=os.environ.copy(), stdout=output,
                                    stderr=subprocess.STDOUT, text=True, timeout=100)
        except subprocess.TimeoutExpired:
            output.seek(0)
            pytest.fail(f"{name} exceeded 100 seconds:\n{output.read()}")
        output.seek(0)
        assert result.returncode == 0, output.read()
