## T4 ordered session-update custody: ready for parent review

**122 production lines deleted**, measured against merged173/main c348ca5b: Agent loses ordered RPC, validation lock, synchronous RPC facade, rejection handler, eleven-arm effect dispatch and session-reset mutation. SessionNotificationOwner owns ordering/admission/SDK validation/publication; SessionUpdateEffect concrete declarations own all eleven existing external cases with shared chunk behavior inherited. Exact direct SDK/test callers migrated; deletion guard prevents root methods returning. External ACP format remains owned by official SDK, original payload/extensions preserved, no parallel protocol or codec.

Actual SessionBinding replaces primitive controller session storage (single state, no epoch/token mirror) and AgentController.bind_session owns reset effects. ClientSessionRequest captures this binding plus existing ProcessDisposition. Pending validation cannot publish after either A→B→A binding replacement or process replacement with the same session string. Initial native notifications before session/new binds an ID remain admitted by the captured initial binding, matching existing startup semantics. Existing typed SessionUpdateValidation owns its rejection query.

Base includes current main c449 plus merged173 c348ca5b. Scope claimed to Noether176/Tesla175 before edits; no App/Prompt/preparation/source/history/db/render-protocol changes. Exact shared renderer addition is only SessionUpdateValidation.rejected, not renderer execution. Inherited Agent.session_id public contract remains; controller's primitive session_id storage and reset body are removed. No mixin/facade RPC, per-boolean family, compatibility alias or new operational scheduler.

### Evidence

- focused-final.log:8 passed (registered real RPC/SDK pending validation binding/process replacement, declaration-only new effect, real terminal lifetime cases, deletion guard).
- native-complete.log:exit0 noneditable installed Toad on core **efcdf493**, Textual **609b74bf**, actual native **d396**. One localhost provider request. Normal App/Pilot physical first input/native reply painted; partial permission merges existing tool update, physical grant; actual terminal execution/output painted; canonical channel route/return preserves same Agent/terminal and draft/Document/undo; pending permission survives detach/reattach and physical reject; actual ACP new-session and stop cancel pending requests. ACP trace final-acp.log.gz.
- First earlier pair also passed. Current pair first RED was isolated missing pi-comms-native entrypoint after old-core uninstall: actual ACP NotSent/no provider recorded, repaired by installing exact current core package. Next REDs were stale/incorrect test App owner callers after169 removed root API. Final test invokes existing NavigationTarget.open with real NavigationContext. REDs retained, no product catch/retry/suppression. Existing PTY completion OSError(5) diagnostic remains; journey exits0.
- Latest authoritative NRA/refactor-audit catalog reread. IMPL-1/4/5/8, MEMB-1, IDEN-1/3/8, BOUND-1/2, TIME-3/9. Per-file foreign-absence/chain-term/excess500 ratchets PASS for all five changed production files. Agent965→853 for this slice; still853, so not claiming whole T4/god-class closure.

Native input/reply and ACP transport are real. Controlled file/terminal/permission requests use the installed Agent.server.call registration, not claimed model-generated native tool calls. New-effect declaration experiment proves effect selection/behavior only; official SDK still owns admitting supported external cases. No paid calls, live mutations/history replay or CI wait. Parent owns integration and actual affected LIVE entry gate.

### Existing exact command

```sh
AC_NATIVE_COPIED_PACKAGE=/home/ts/.local/share/agent-comms/native-current-d3967e8b6ee0cf28/node_modules/@earendil-works/pi-coding-agent L0A_EVIDENCE="$PWD/evidence/session-updates/native-complete" TMPDIR="$PWD/.artifacts" PYTHONPATH="$PWD/tests" PATH="/home/ts/wt/toad-context-measurement-sol-20260929/.artifacts/installed/bin:$PATH" timeout 60s /home/ts/wt/toad-context-measurement-sol-20260929/.artifacts/installed/bin/python tests/client_session_native_installed_pilot.py
```

Parent review correction173 d28a567d is included and now on main. No extra unchanged matrix needed; remaining gate is parent integration/live publication.
