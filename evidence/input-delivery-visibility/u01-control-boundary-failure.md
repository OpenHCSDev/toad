# Original u01 pre-Enter control failure

The preserved run is `/home/ts/wt/g458g/u01`, stage
`runtime-native-source-queue-cohort-20260930`, Core
`970bc527f4ddd9b3bde5522dc671aea11fd27ece`, Toad
`d3ba4cf330acd4d2eec6cd806fab8113c3a046ec`, Textual
`6b5895fa0a72aeec2aeaef7206d5debfa0c1803c`, driver
`f265a9f240da62e51e7736c4299c7388cca64ecc`.

Actual exit was 1 after 43.753 seconds. `acceptance-failure.txt` identifies the
first `submit_editor` pause, before editor click or Enter. Its 183 original
compositor frames span 36.027 seconds and contain no submission. The original
provider report has `requests: []`, `errors: []`; no new original input or
provider request was made. This does not demonstrate a pending-caption product
failure. The negative raw run and its disposition remain unchanged.

The fixture suspended its original private worker before revealing/clicking the
editor. The frozen installed `Conversation.on_agent_ready` first sets
`agent_ready`, then queues `goal_observation.refresh` and
`delivery_observation.refresh` on the same widget. The latter awaits
`controller.request_owner('input_dispositions')` without an enclosing timeout.
`Pilot.pause` places a callback behind each widget's queued messages and waits
for all of them. A deliberately stopped worker cannot answer that metadata
read. This is a source-backed causal diagnosis: the failed run did not retain
an async task stack proving which individual callback remained blocked.

The correction uses the original physical editor preparation helper once:
reveal, await native screen readiness, physical click, insert draft. The
specialized installed journey then completes the native widget/draft barrier
while the worker is running. Only immediately before actual Enter does it
enter the existing private-worker hold. The original pidfd/private-root and
ProcessIdentity attestation, final SIGCONT and fd close, nonblocking canonical
input-store check, actual pending ANSI requirement and strict exactly-once
pending-to-native-chat raster oracle are unchanged. Base and specialized
journeys dispatch through `InstalledApp.submit_editor`; no optional second
control or copied click sequence is added.

The three affected driver modules import against this exact staged package;
`git diff --check` passes. No additional app, native process, provider call,
public mutation, input replay, timeout increase or oracle waiver was made.
Einstein owns the sole fresh installed run after receiving this checkpoint.
