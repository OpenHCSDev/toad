# Installed log navigation lifetime

Base Toad4147eb1, core0931c47d, Textualc974, native5fde. The unchanged
installed log UI pilot on the actual saved user ACP log hung after preview
navigation. In-process task stacks show the markdown handler awaiting navigation
while navigation awaits removal of that same markdown message pump. The original
timeout and diagnostic failures remain separate from passing evidence.

ConversationMarkdown now submits the existing App preview operation as an async
callable worker. The originating message pump returns before its retirement.
No second navigation mechanism or pre-created coroutine is introduced.

The noneditable installed candidate passes the complete actual log UI pilot:
two fresh app mounts, clicked link, parsed observed compaction/quota failures,
Events/Raw, horizontal selection, wrap, narrow resize, appended stderr,
Earlier/Latest paging, missing-file recovery, close/reopen and ordinary Unicode
file paint. The final encoded-log-ui receipt additionally uses a real log filename
with spaces and Unicode through the external toad-file URI. log-disk records
bounded reads, exact raw reconstruction and cross-window failure recovery.

Delete agent_failure_log_pilot: it injected an Agent through set_reactive without
the current source/controller binding and intercepted a retired screen method.
Attempting actual navigation with that invalid fixture timed out (failure-link).
The maintained actual installed log UI pilot protects the visible diagnostics,
encoded-path click, file reading and navigation lifetime without mocking preview.
This is UI/log acceptance, not proof of a live provider send or the separately
reported user RecursionError. That crash remains under investigation.

Combined with merged14613dd52b: actual installed pending-mount cancellation/source
replacement passes, actual installed inline/diff grant/reject/stop passes, and two
family/deletion guards pass. Core0931c47d and Textualc974 unchanged.
