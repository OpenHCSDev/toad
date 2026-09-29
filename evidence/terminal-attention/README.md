# T4 terminal attention / notification lifetime

**148 production lines deleted first; 218 added, net70.** ToadApp1638→1510
lines (128 removed); largest new owner is TerminalAttention68 lines. Complete
source `a80a6ab6`, base currentmain `16cfcb18` (includes165). Scope is a remaining
originalT4 App state owner, not wholeT4/wholeT9 completion. Claims are directly
on Tesla160 comment5885696027 and Carver165 comment5885696272; no edits to their
viewport/body/preparation/input-history/failure feedback implementations.

## Owner / caller closure

- Delete App flash counter, blink flag, optional timer, four title fields and
  watchers; exact live source identity replaces increments that leaked when
  multiple queued Ask requests cleared with only one decrement.
- TerminalAttention owns pending widget sources. Prompt contributes once while
  its actual current Ask exists, releases when its queue empties and on unmount.
  PermissionReview contributes its own exact screen until the existing request
  exits; require/delivery/watch are all inside the existing try/finally lifetime.
- Detached/Quiet/Blinking TerminalTitle cases own publication/start/stop. The
  detached case permits preferences before App mount and ignores late retirement
  after close; live blink settings reconcile the existing request owner. Icon/
  Pointer TitleFrame cases own their presentation/advance. No own counter/flags,
  phase enum/string dispatch, external timer probes or second notification roster.
- Existing NotificationPolicy declarations retain focus admission and share
  real notifypy delivery on their parent. Textual keeps its own toast collection
  and presentation; delete App's duplicate collection/refresh handling.
- MainScreen title, tab close/mount, Prompt Ask, permission, Conversation notify,
  About and telemetry terminal identity callers now use this actual owner.
  Terminal environment detection moves once; no telemetry behavior expansion.
  Preserve existing workspace/store title selection semantics.
- No aliases, reexports, shims, converters, FieldCodec subclasses, or parallel
  lifecycle/metadata store. Settings JSON/external ACP/D-Bus/OSC contracts unchanged.

**Latest exact authoritative skills reread:** NRA SKILL and canonical archive
refactor-audit SKILL/pattern README (principle13/foreign absence/chain dominant
kind already active). IMPL-8/10: state and transitions owned together. IDEN-1/3:
actual source identity and detached state, no scalar/restated absence authority.
IMPL-4/5: shared policy delivery on existing declaration parent. TIME-9: every
old callable/field removed, no wrapper to an old shape. AGENT-8: the private
D-Bus receiver's methods are declarations with derived protocol membership.
New case BadgeTerminalTitle overrides one icon method and inherits reconciliation,
publication and application callers; no edits to App or a roster. Actual Linux
PTY receipt contains its badge alongside normal/pointer titles.

## Actual installed affected path: PASS exit0

Run the existing native fixture once per concrete correction in a bounded
physical PTY; no fake Agent, UI, loader, renderer, framework, driver, permission
future or notifypy backend. Only the loopback model response and test-owned
D-Bus receiving endpoint are controlled. The latter runs on a private real
session daemon, so the owner's desktop never receives these notifications.

Actual imported noneditable ownwheel, core`a01927ed`, Textual`1738abd8`, verified
native`d3967e8b6ee0cf28`; exact locations/metadata in installed-versions.json.
The normal installed App runs the real LinuxDriver (`headless=False`) with the
actual PTY window160x44. Saved physical Pi input/reply is committed before UI
open, actual ACP attaches and actual compositor must paint saved response.

1. Three real Conversation Ask requests enqueue; each question paints and actual
   keyboard Enter answers it. One source remains, then quiet/zero pending.
2. Cancel a queued Ask, remove current, preserve another exact source. Live
   blink preference stops actual timer advancement and restores/restarts title;
   exact repeated retirement is idempotent.
3. Controlled incoming edit request enters the **actual attached Agent's installed
   ACP server.call boundary** (not a native-generated tool request). Actual
   PermissionReview diff paints, exact screen owns blinking; physical `a` selects
   Allow, existing response future settles, screen/attention retires. This proves
   the modified permission caller; it is not claimed as a new Pi/MCP permissions
   wire test.
4. Declaration-only badge title uses unchanged inherited publication/driver.
5. Actual notifypy→notify-send→private D-Bus receives question/permission/warning
   notifications. Markup stripped; information and Never policy do not deliver.
6. Real tab selection/return and resize112x34 retain original draft Document/
   EditHistory. Native journal bytes and one provider request are unchanged.
   Final real terminal OSC title is normal icon, not pointer; sources empty.

`installed-final.log`, `journey.json`, `terminal-titles.json` and compressed
physical terminal capture are the final same-source receipt. GuardPASS removes
all retired APIs across production; packaged per-file ratchetPASS has no positive
class/chain/foreign-absence/codec/type delta. GodClassExcess App−128,
ForeignAbsenceProbe App−1; other measures zero. No full-suite/global NRA timing,
Tesla rendering/performance target, live deployment or CI claim.

Real-path corrections recorded: initial effect published before a screen existed
(startup-lifetime-red.log); corrected with detached lifecycle, not a guard/default
screen. PTY needed its physical window set (zero default size hid saved paint).
An interim test incorrectly assumed Timer.stop retained a done `_task`; replaced
that private-shape assertion with actual stopped frame advancement. Product
assertions retained. Native/real-UI/DBus/PTY full journey is green on final source.

## Reuse exact harness in parent's next immutable pair

```sh
cd /home/ts/wt/toad-terminal-attention-sol-20260929
TMPDIR=$PWD/.artifacts \
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-d3967e8b6ee0cf28/node_modules/@earendil-works/pi-coding-agent \
L0A_EVIDENCE=$PWD/.artifacts/installed-attention \
timeout 110 .venv/bin/python tests/terminal_attention_installed_journey.py
```

For a candidate use its Python and verified native path in the same command;
normal installed imports determine tested code, not source PYTHONPATH. No new
matrix needed. Parent owns merge/pins/affectedLIVE gate/install; CI deferred.
Only own~/wt source/env/evidence plus small disposable private wire /var/tmp
(required by current core fixture); no shared checkout/live store writes,
replay, restart or paid calls. All test owners/native children/private daemon
reaped after actual gate; resource receipt records cleanup. Current blockers:none.
