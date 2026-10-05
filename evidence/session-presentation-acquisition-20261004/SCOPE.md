# Session-owned acquisition and operational observer custody

Source working checkpoint stacked on the frozen #446 source/control branch.
No #446 control or package candidate changes. No installed, provider, native,
profile, physical or CPU qualification is claimed by this draft.

## Existing owners

OperationalSessionPresentation already retains its actual Conversation, editor
state and OperationalSessionSources. NativeSessionSurface previously constructed
and mounted that widget, read the presentation's agent/state and restored/cleared
its editor state. The workspace owns actual admission, not those presentation
resources; logical WorkspaceSource selection remains a separate fact.

The presentation now acquires its original view through an async context on the
existing class. The workspace sets its original admitted view at the yielded
mounted resource, before attachment/restoration can await. Presentation then
restores editor/reader state, prepares the actual history, displays the resource
and resumes an existing native session. The original workspace lock, view-derived
widget property, recency/resource budget and retirement/disposal remain intact.
Cold on_mount still owns initial startup; warm activation retains its separate
startup call. There is no additional widget store, state mirror or startup flag.

OperationalSessionSources.wire owns pre-mount agent binding and the retained
DirectoryWatcher, once per activation. This moves the watcher before
Conversation.initialize_view/start_native_session, which otherwise creates a new
watcher before the old post-mount wire overwrites it. The old NativeSurface
interior agent/editor decisions and post-mount wire caller are deleted (IMPL-12).

DirectoryWatcher.rebind previously changed only its notification target, leaving
its CoreEventStream subscription on the old receiver. Stop subsequently retired
the new receiver's absent subscription. Rebind now retires the old receiver's
subscription and subscribes the actual new receiver under its original delivery
lock. The original watcher, observation manager, source revision and stop/join
remain; no process restart or second subscription store is introduced.

## Source evidence and limitations

Original refactor-audit Package before: Toad288 production,395 tests,41 tools;
retained Text59 249; declared Corea38 316 Python modules, zero parse omissions.
These are dependency source modules, not installed347/Core assets. The indexed
owner/caller/field census is lexical and does not prove external dynamic aliases
or runtime equivalence. All indexed acquisition, watcher creation/rebind/close,
core subscription and original workspace/frame admission consumers were read
against their declarations. Only two production files change.

The next affected boundary needs actual cold/warm/evicted remount and retained
watcher/agent/shell/permission/editor/read-position preservation, subscription
handoff and whole close. The pending #446 three controls continue at their
frozen pre-TC1 production scope and do not qualify these changed bytes. No extra
holder, App or native purpose is inferred. The current draft is source-only;
source controls and affected installed application come after coherent closure.
