# Paired B2 / L0a Toad channel closure

Branch `refactor/channel-deletion-closure-20260928`, base Toad main #73.
Install in lockstep with core B2; parent owns pins/deployment and quiet catalog cutover.

- CommsChatView reads current saved-view declaration, disables composing with explicit read-only status, and refuses direct submit before publication. Existing target/messages are displayed in the normal channel path.
- Removed every current `set_channel` caller from Toad tests; use exact tag channels with actual membership. Union view behavior is tested as read-only history, not writable compatibility routing.
- `current-format-mounted.log`: exit0, keyboard opens saved view from normal sidebar; original-target and exact-channel transcript visible, pin preserved, composer disabled, direct submit rejected, bus bytes unchanged.
- `exact-channel.log`: exit0, full ordinary channel send, member/participant updates, tabs/drafts and pin behavior. The receipt's old print label says union; this test was migrated to the exact engineering tag.
- No provider calls, global edits, live writes or restarts. Mounted fixture has a guarded main entrypoint.

The core handoff owns one-shot catalog conversion instructions. Runtime Toad contains no converter or old channel interface.
