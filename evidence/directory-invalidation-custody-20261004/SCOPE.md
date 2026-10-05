# Directory invalidation custody

Source base: 38e175f4d1d03d55b9c4d4e299a30977d49dea3d (450).

`DirectoryWatcher` owns the pending filesystem invalidation. A queued
`CoreEventMessage` is delivery, not consumption: retiring its subscription must
leave the original invalidation pending. Rebinding to a screen without a
DirectoryChanged handler must also leave it pending for the actual Conversation.

Keep the existing watcher observation/revision and recipient lock. Consume at
that watcher's current Conversation; delete Conversation's `_directory_changed`
copy and the repeated terminal/turn publication algorithm. Generic CoreEventStream,
SurfaceBinding and session presentation lifetime remain their existing owners.

Claims: directory_watcher.py and Conversation's directory handlers only.
Heis owns session_presentation.py integration. Source reasoning and complete caller
migration precede any final affected checks; no holder or execution purpose is
claimed. Pattern IDEN-5 (split fact), IMPL-12 (repeated implementation).

Before: NRA Package parses src/toad 288, tests 395 and tools 41, zero omissions.
Attribute/name matching is source evidence; dynamic aliases and external subclass
behaviour are not proven by this enumeration.

## Published implementation

Production checkpoint: bf9baf771d6e285b65a55befe1170d886e02f84f. Two files, 28 added and 31 deleted lines.

`notify_if_visible` and `rebind` share original delivery custody. Queuing
a publication no longer consumes `_dirty`; `consume_change` clears it only for
the bound native recipient. Busy delivery leaves it pending. The same watcher
can therefore cross a retired subscription or a handlerless MainScreen without
losing its filesystem change.

Conversation event, terminal completion and turn completion use `check_directory`.
It updates original prompt path-search and project-panel publications together.
The independent `_directory_changed` fact and unused `is_watching_directory`
projection are deleted; original disabled-observer fallback is retained.
After Package roots: 288/395/41, zero omissions. Syntax/diff checks passed.
No App, watcher process, provider, prefix access or installed qualification was
performed; this remains a source checkpoint for the integration owner.
