# Canonical layout preferences

UiSettings owns column enablement, column width and scrollbar choice. Current
App and MainScreen reactive fields copy those facts; three session constructors
also have to remember to bind them. IDEN-5 and IMPL-12 describe the duplication.

Use the existing Conversation renderer and its existing PreferenceChanged
subscription to read the original settings at initialization and on declared
preference changes. Delete App/MainScreen copies, bindings, three copying
effects and the unused Conversation.column variable. CSS remains a rendering
resource; scrollbar class names derive from the original Scrollbar family.
No new type, registry, timer, compatibility facade or native runtime changes.

Heis granted the preference declarations/watchers and constructor consumer
methods; no viewport/frame/style/compose work overlaps. Existing native
initialize_view and preference handler are the only additional renderer hooks.

Before source: NRA Package parsed 289 production and 391 test Python modules,
zero omissions. Lexical AST references do not prove dynamic resolution; ANSI
and grid column locals are unrelated. SettingsGroup/SettingKind owns values and
change notification; CoreEventStream/PreferenceChanged owns publication.

Validation comes after complete implementation: original installed settings
editor plus actual App chat construction/change/tab return, private settings
save/reopen. Detect stale width/scrollbar projection and missing new-view
initialization. No provider calls or public inputs. Source tests alone do not
claim physical UI/native/performance readiness.
