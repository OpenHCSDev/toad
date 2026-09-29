# Restore retained native history visibility

AgentReady accidentally constructed LocalAgentPresentation instead of initializing
its Textual Message base. ACP load and transcript delivery succeeded, but the
ready notification lacked Message state, leaving Conversation's loading overlay.
The fix calls super().__init__(); the unrelated presentation object is deleted.

Actual installed Toad with the live retained pr95-selected-pi-summary-owner
session reproduced the stuck UI (45-second timeout). With this one-line correction,
the same native ACP/session path reaches ready, mounts its TranscriptHistory,
removes the loading overlay, and completes Agent.run without an exception.
No prompt, store reset, input replay or live owner stop. Receipts retained;
no claim that earlier ACP attachment-only checks proved visible history.

Production diff: one line added, one deleted. Core4510dddf/Textualc9743801 unchanged.
Parent owns immediate installation. CI deferred.
