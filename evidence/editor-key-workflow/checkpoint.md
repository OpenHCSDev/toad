# Editor focus/key workflow investigation

User report: the same input accepts printable typing but intermittently rejects
Backspace/Delete and Left/Right. PR202 owns this investigation; parent owns
canonical activity/input/cancel lifecycle. Schrodinger owns failed attach and
owner restart recovery. No overlapping shared-editor claims were found.

Source b554ed12 and actual installed old pair8616/Corec1/Textual412/native776
passed the provider-free actual App Pilot journey: click editor, insert,
Left/Right/Backspace/Delete, actual undo, Tab traversal, physical A/B/A.
The same two versions passed actual LinuxDriver terminal delivery through the
existing e2e_pty owner: SGR mouse click, raw Left CSI-D, DEL Backspace, Delete
CSI-3~, Right CSI-C, Escape/Tab/ShiftTab, actual A/B/A tab clicks. Each of thirty
observed key phases checks the same focused PromptTextArea, actual document,
text and cursor. No native/provider input, live-owner action, or global mutation.
Source and installed paths are recorded separately; terminal traces capture
actual message receivers, key consumption and accepted binding namespaces.

The real user defect remains UNREPRODUCED. These are healthy local editor tabs,
not proof of failed attachment recovery, active/post-cancel, large saved history,
or the running user's stuck view. No speculative production deletion/focus
patch was made. Native active/post-cancel check awaits the shared fixture slot;
we do not restart/replay the user's owner to obtain a receipt.

Failed probe setup was not acceptance: missing test-only pyte/wcwidth imports,
unsupported public run hooks, PTY output backpressure and a non-atomic observer
JSON write were fixed in test instrumentation. Test dependencies live only in
.artifacts/terminal-dependencies; the installed package source was not changed.
No Ctrl+Y redo claim: that key has a declared Send now priority binding.

Commands (60s timeout each, serial):
PYTHONPATH=src:tests or tests; TMPDIR and EDITOR_KEY_EVIDENCE point to owned
.artifacts/editor-key-* directories; paired Python runs
tests/editor_key_workflow_pilot.py. Real terminal runs
tests/editor_key_terminal_journey.py through the same interpreter; installed
old-pair Python uses PYTHONPATH=tests:.artifacts/terminal-dependencies.

Original small887installed native return and geometry readiness remains
independent of this new defect. WholeTC1 and live large-history firstpaint remain
open. Parent activation does not wait on the final performance target.
