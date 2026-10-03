# Canonical layout preferences

UiSettings owns column enablement, column width and scrollbar choice. Current
App and MainScreen reactive fields copy those facts; three session constructors
also have to remember to bind them. IDEN-5 and IMPL-12 describe the duplication.

Use the existing Conversation renderer to read original settings at
initialization. The existing descriptor effect mechanism invalidates layout
on all original WorkspaceSessions views when any of the three values changes. Delete App/MainScreen copies, bindings, three copying
effects in favor of one shared invalidation effect, and the unused
Conversation.column variable. CSS remains a rendering
resource; scrollbar class names derive from the original Scrollbar family.
No new type, registry, timer, compatibility facade or native runtime changes.

Heis granted the preference declarations/watchers and constructor consumer
methods; no viewport/frame/style/compose work overlaps. Existing native
initialize_view and apply_layout_preferences are the only renderer hooks.
Textual App.query starts from default_screen; explicit WorkspaceSessions.views
ensures parked views still update while a Settings modal is open.

Before source: NRA Package parsed 289 production and 391 test Python modules,
zero omissions. Lexical AST references do not prove dynamic resolution; ANSI
and grid column locals are unrelated. SettingsGroup/SettingKind owns values and
change notification; CoreEventStream/PreferenceChanged owns publication.

Validation comes after complete implementation: original installed settings
editor plus actual App chat construction/change/tab return, private settings
save/reopen. Detect stale width/scrollbar projection and missing new-view
initialization. No provider calls or public inputs. Source tests alone do not
claim physical UI/native/performance readiness.

## Published checkpoint

Source implementation: ed67412a; installed journey driver: aa9ca8ca.
26 production lines added, 48 deleted across six files. No new owner types.
All three constructor bindings, six reactive copies, three copying effects and
one unused Conversation variable are gone. Shared descriptor invalidation
reaches original WorkspaceSessions views; Conversation owns native paint.

After AST: 289 production and 391 test modules parsed, zero omissions;
remaining column terms are original UiSettings descriptors or unrelated ANSI/grid
operations. Native CSS/max_width resources are projections, not semantic stores.
Wheel contains 320 assets byte-identical to source.

Final installed App check is pending fresh style22 loan from Heis after393
archive and borrower closure. Bohr confirmed485 was serving19 live processes;
no mutation occurred. Parent subsequently published395 to334, which remains
protected. Neither old receipt names nor a default switch grants a donor loan.
No new environment, native copy, provider call or public input was started.
