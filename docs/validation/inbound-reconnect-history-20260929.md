# Inbound history after reconnect

Owner: this branch. Scope: channel assignments reappear as fresh tail blocks after reconnect or reopening a recipient.

The existing `Conversation._show_assigned_inbound` checks only mounted incoming blocks. Native saved-history coverage and old assignments without native input must retain their recorded placement and handling. Reuse existing transcript and sequence ownership; do not introduce a seen-message store.

Acceptance: installed Toad with private saved-state fixture, real ACP/owner/native process and controlled localhost provider. Old handled channel messages survive reconnect, A/B/A and reopen exactly once per wire identity; late handling updates update that presentation; new messages appear; restoring old records starts no provider call or turn.

Status: investigating; not ready or live. Shared-file regions communicated to PR199 and PR202 owners.
