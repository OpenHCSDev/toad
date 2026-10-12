"""Toad-side observers that Core's own acceptance tests load by file path.

These are not tests of this suite and nothing here runs them. agent-comms loads
``mcp_permission_observer.py`` through ``AC_MCP_TOAD_ADAPTER`` (tests/test_mcp_acceptance.py) and
``human_input_observer.py`` from its ``--toad-driver-dir`` (tests/turn_context_installed_journey.py,
tests/test_native_context_inspection.py). Each opens the real Toad app on the wire Core's test owns.
"""
