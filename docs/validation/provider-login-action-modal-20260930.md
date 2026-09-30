# Provider login action/modal closure

Owner: Einstein. Base: Toad8512c2cb (includes239 and241).

## Required relation

Every ActionModal command carries the existing CatalogCommandAction behavior owner, its AgentDefinition and its executable command. Conversation provider-login must construct LoginAction from the advertised terminal auth method, rather than the deleted positional action/name interface. ActionModal remains the one PTY dialog and LoginAction owns success dismissal. Trace all constructor consumers before changing them (IMPL-4, TIME-3); no adapter or second dialog.

## Original failure

Saved terminal trace: /home/ts/.local/state/toad/logs/Terminal_crash_2026-09-30T12_15_29_613337.txt. WorkerFailed wraps TypeError: ActionModal takes4 positional arguments but5 were supplied, plus2 keyword-only. The provider-login terminal branch still supplies login/name/description/command.

## Scope and acceptance

Conversation.action_provider_login only; all ActionModal callers census; existing family behavior and completion. Heisenberg242 owns other Conversation resource/history methods. Validate actual installed Toad login method selection, PTY/native credential handoff to the user credential boundary and cancellation without credentials, account changes, paid provider chat, authentication completion or public owner mutation. Candidate must pass before defaults are published.

## Source checkpoint

Full source/test census finds two production ActionModal calls. CatalogCommandAction.apply already supplies typed action + original AgentDefinition + edited command. Conversation.action_provider_login was the sole stale call; it now binds its advertised terminal command through Command.bind("login") and supplies agent.definition by identity. LoginAction retains success auto-dismiss and explicit failed-command dismissal. Fork/goal dialogs do not call ActionModal. No constructor or alternate reader was added.

Production delta: one file,3 added /3 deleted lines. The3 deleted lines are the obsolete action/name/description positional arguments, replaced by the2 typed argument expressions plus the existing Command import. Existing env/cwd/command and reconnect lifecycle unchanged.

## Actual installed acceptance

READY scoped candidate test: 31.88662995697814s. Installed noneditable candidate82f454cd with Corea80/Text2e/SDK0.12.1/nativececa; actual ordinary toad-comms launcher selected candidate only in the isolated st/Xvfb display. Actual AgentInfo, ConnectProvider, advertised ChatGPT method and Cancel clicks used committed compositor hit targets, not guessed pixels. Native Pi visibly reached its trust-project prompt, the first user approval boundary; authentication and /login editor preload were not entered or claimed. Cancel returned to the same conversation.

The test uses an owned empty Pi account directory and clears inherited provider API keys. Native created auth.json{} with zero entries; no credential/account changes. No prompt, provider request, trust decision, auth completion, public owner restart or defaults change. Original retained41MB source/owner/active turn byte-identical before/after. Recorder cleanup has zero remaining owned PIDs and errors.

[Ready receipt](../../evidence/provider-login-20260930/ready-receipt.json) includes exact stage/provenance and raw paths; chooser/native handoff/cancel PNGs accompany it. Full raw movie, native DTOs and both failed wrapper receipts remain protected.

The first attempt failed in the new generic widget helper converting a float center to a native cell, before any login; corrected to existing integer hit-target convention. The second actual journey completed, then the wrapper's no-auth-file oracle falsely rejected the native empty auth store. Corrected to zero credential entries and reviewed the retained artifacts read-only; no third GUI journey. Both failures remain recorded.

Status: useful installed checkpoint ready for parent review/merge/publication. No default-live or full authentication-completion claim.
