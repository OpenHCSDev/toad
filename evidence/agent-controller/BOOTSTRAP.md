# Production bootstrap native regression

Toad source base: merged127/main08d464bf; affected installed Agent/UI source identical to12748f34fd. Installed noneditable core27876855582f4facbdb7cf333ee42f9c42414ef6a1b and Toad wheel in own .venv. Product imports resolve from that .venv; no PYTHONPATH product override.

Deleted MutationStore plus four private schema installer imports and the entire manual setup block from l0a_native_installed_pilot.py. Fresh Comms.messaging.initialize_private_initial_protocol() is now the sole initialization; normal ACP detached owner launch performs runtime bootstrap. No fixture fallback installs.

Actual native path exit0: prompt execution, queued input consumption/native mapping, cold reattach, DM reply, channel active/idle notification decision, stopped owner reopen, zero model requests during idle observation. Loopback HTTP provider only, no paid calls, production launcher unchanged. Bootstrap deletion guard1passed. Receipt: production-bootstrap-native.txt.

Production bootstrap requires core278 or later; parent owns current core pin/integration and live cutover. No product pins or live installation changed in this test-only checkpoint.
