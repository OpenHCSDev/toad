# Sidebar resize ownership

The shared header spans the workspace and has no sidebar-dependent padding.
Deleted WorkspaceScreen.align_tabs_to_sidebars and every Main/Comms session
consumer, including two broadcast handlers that queried the same shared header
for every mounted tab on each sidebar width change. Existing header CSS owns
padding0; WorkspaceHeader still receives SidebarLayoutChanged and the original
WorkspaceChrome applies sidebar geometry. No event, state mirror or cache added.

Source738 modules parsed without omissions. The actual native resize App passed
left/right drag, capture, slider keyboard/endpoints, ANSI/RGB hover and collapse
on the installed Core275/Textual48cf with changed Toad source. This is source-App
verification, not installed Toad delivery or a measured latency gain.

The original resize check assumed a final Click must land on a track that resizes
on press. Migrated to actual captured press/release with width assertions retained.
Tab history initially refused two obsolete helper relationships: conversation on
WorkspaceScreen instead of retained SessionView, and native mode switching instead
of app.select_session. Corrections migrate the existing helper; no production alias.
Original failed logs remain in /home/ts/.cache/agent-scratch/sidebar-header-ownership-20261007.

Corrected original tab-history App passed Back/Forward, branching, closed tabs,
draft retention and horizontal scrolling, empty stderr. No accepted resize check
was repeated after it passed.
