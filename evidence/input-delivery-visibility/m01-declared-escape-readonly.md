# M01 declared Escape: bounded original-source diagnosis

Original evidence stays in `/home/ts/wt/g458g/m01`; no capture or provider run
was added for this review. Core970/Toadd3ba/Text6b and driver3a3 are frozen.

`pointer-target.json` attests the physically expanded #team member beta,
ThreadRow region `[2,11,57,2]`, native hit identity and actual right click.
`screen_after_click` is ContextMenu. The original driver physically clicks the
Fork menu item, waits only for `isinstance(app.screen, ForkDialog)`, saves an
SVG, presses Escape, and times out waiting for the dialog to disappear.

The installed ForkDialog declares Escape/cancel and `action_cancel` calls
`dismiss(None)`. There is no fork-cancel button. An earlier unsupported-Escape
attribution was incorrect and retracted; the original negative remains.

The actual fork-dialog.svg is 2,051 bytes with viewBox height 74.4 and an empty
terminal text matrix (only the outer InstalledApp title). The preceding
after-rightclick.svg is 70,943 bytes. Offline replay of all 132 original emitted
ANSI frames finds the menu caption "Fork from this thread" at frame 126 but
never the ForkDialog title "Fork from @beta" or name/task/tag controls. Thus
the evidence proves pointer/menu routing and a pushed ForkDialog object;
it does not prove a visibly mounted, focused dialog before Escape.

Frozen source ownership:

- ForkAction.request asynchronously reads the original parent and pushes the
  dialog. Native App.push_screen publishes the new screen-stack entry and
  separately returns AwaitMount for screen/child mounting.
- ForkDialog.on_mount focuses the original #fork-name Input.
- Native Pilot.press constructs the Escape Key and sends it through the
  original driver. App.focused derives from the current screen.
- Native Input only consumes printable key characters, not Escape; it has no
  Escape binding. Toad's declared application bindings have no priority Escape.
- Native Screen's modal binding chain keeps the dialog namespace. The normal
  action route resolves cancel on that original namespace.

No runtime focus, mounted-state, binding-chain or Key dispatch receipt was
retained at Escape, so a driver-before-ready race versus a product mount/focus
or action route fault is not proven. Do not repair this by changing bindings,
adding priority aliases, forcing focus or increasing timeouts from these facts.
Heisenberg owns the product modal/focus diagnosis and any proved correction;
Kepler owns this readonly original-artifact trace. The negative stays tracked
separately from the queue/fork-submit journey. Original teardown also failed
waiting for its worker; Einstein preserves that separate failure and cleanup.

## Related original modal failure: g458h/u01

The next original capture is preserved at `/home/ts/wt/g458h/u01/proof`.
Its pre-teardown JSON records current ContextMenu, no child DOM, no focused
widget and zero provider requests after the original 20-second item wait.
The receipt identifies Core970, Toad85d45b51, Text6b and driver214aaacb;
this is a different product candidate from m01, not an unchanged reproduction.

The native route registers the screen and starts its message pump before
publishing it on the screen stack. MessagePump._pre_process dispatches Compose
then Mount before processing keys. App._check_bindings uses the original
Screen._modal_binding_chain; even with no focused widget this includes the
modal itself. Input.check_consume_key only consumes printable characters.
Thus lack of focus alone does not explain Escape ignoring the declared cancel
binding. The retained evidence has no modal message-pump stack or key dispatch
record, so it cannot identify the stalled native lifecycle operation.

There is also a definite independent harness defect: wrapper.log lines 295–331
and 712–748 show multiprocessing.spawn importing the original preflight script
as __mp_main__, executing its unguarded asyncio.run(main(...)) at line 56 and
failing to recreate the existing fixture directory. Einstein owns correction of
his original entrypoint main guard. That failure is proved; its causal relation
to the empty modal is not. Heisenberg owns the concrete modal lifecycle trace.
No production bindings, focus state, timeout, oracle or installed source were
changed for this review. The original Escape failure remains open separately.

## Original M01 recheck — 2026-10-01

The accepted row → ContextMenu → ForkDialog route and failed Escape are retained
as separate observations. Readonly replay of the original 132 ANSI packets finds
the menu caption in packets 127–130 (one-based numbering), and no dialog caption.
The observer records ANSI, session, submissions, queue and chat geometry; it has
no focused widget, modal mounted state, binding namespace or key-dispatch field.
The teardown stack artifact contains only a profiler permission-denied message,
so it supplies no stalled modal task stack.

Frozen Textual `app.py:4123` forwards a non-priority key to the original focused
widget or current screen. `screen.py:434` derives bindings from that focus and,
when focus is absent, includes the current screen itself. The modal boundary at
`screen.py:468` retains the ForkDialog namespace. `app.py:3968` invokes its
declared cancel action. Consequently, absent focus alone does not explain this
failure; screen-stack publication alone does not certify mounting or paint.
No retained event proves a wrong target, suppressed binding or completed cancel.

The same independent entrypoint defect is also present in **M01 itself**:
`/home/ts/wt/g458g/menu-control.py:35` runs the acceptance at import time without
a main guard. Original `wrapper.log:311` and `:722` show renderer spawn importing
that script, followed by fixture-directory `FileExistsError` at lines 329 and
740. This is a concrete driver lifecycle defect owned by Einstein. These child
failures do not prove the cause of the Escape failure.

Disposition: Heisenberg retains product modal lifecycle/focus ownership; Kepler
completed the bounded original-artifact trace; Einstein owns the entrypoint.
The missing original key/pump receipt prevents a causal product fix from this
capture. No new binding, focus copy, provider call, capture, timeout change or
production edit was made. Queue/fork-submit acceptance is not blocked by this
separately tracked negative.

Original input-frames SHA256:
`93322845c1fb0989a92a2b9c588f297acffc98fc588cd29891f5eee39e138186`.
Original Escape failure SHA256:
`de4723505cbd07fe7192be082ada2498c9fa3d2604a44ac3d73d487300a6e3c8`.
