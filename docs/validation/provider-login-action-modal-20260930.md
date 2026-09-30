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

Status: source checkpoint published; installed candidate acceptance pending. No readiness or activation claim.
