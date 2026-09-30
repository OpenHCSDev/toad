# Shared fork helper native readiness contract

The original M01 negative remains separate: a ForkDialog object existed but
its retained SVG/ANSI never demonstrated painted name/task/tag controls. Its
declared Escape failed; that is not an unsupported action and is not waived.
The existing helpers previously admitted only screen type before interacting.

One shared `runtime_fixture.wait_fork_dialog` now derives readiness from the
original current native screen and child resource: dialog mounted/attached,
original #fork-name Input mounted/attached, dialog/app focus both that Input,
nonzero geometry inside the terminal and original native hit test at that
geometry returning that exact Input. It neither sets focus nor constructs a
second readiness state, widget registry, alias or action bypass.

All existing positive fork-dialog waits were migrated: first-fork main and
content-only journey, saved-state fork journey, goal-state journey and both
command-family cancellation journeys. The original 20-second native wait
budget remains; command-family explicitly retains its original 8-second budget.
Negative dismissal waits and actual Escape/click/submit actions remain intact.
The saved-state optional task field was also corrected from removed Input/value
to the actual installed TextArea/text contract instead of restoring a reader.

This helper is outside Einstein's separately owned runtime_fixture.run_test
cleanup region; it makes no teardown edits. All affected modules import against
the actual frozen Core970/Toadd3ba/Text6b package and diff checks pass. No app,
native process, provider run, original input replay or public mutation was
performed here. Native readiness and whole input acceptance still require the
one integration-owned affected journey after the independently owned sidebar
publication failure is corrected. Do not repeat the frozen failed candidate.
