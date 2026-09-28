# Detached operational Agent owner

Parent-assigned independent slice; Tesla126/116 owns App/MainScreen/workspace/global admission and its caller closure. Branch originally from ready12748f34fd;127 now merged08d464bf. No live installation/launcher/root changes, no CI wait, no paid calls.

## Implemented

- AgentController owns weak optional SurfaceBinding, captured validation resource, session and actual coordination fact. No raw-message buffer or second reducer.
- Agent.attach_surface(view)/detach_surface(view) keep process, sole existing QueueAttachment and permissions operational. Rebind derives active turn/current queue/cursor floors and reads canonical history through existing get_transcript_page.
- Agent.permissions owns typed PermissionRequest futures. PermissionRequest.answer(surface, answer) only accepts the current surface and an offered answer; presentation cleanup does not resolve/cancel the source request. Agent.stop, connection EOF and session replacement cancel pending requests.
- Conversation consumes typed RequestPermission(request), projects asks/diff dialogs and uses public source custody on unmount. Attached default unmount still stops its owner; workspace explicitly detaches before rich retirement and explicitly stops on logical close/shutdown.
- Removed private message-target/future-set mechanism and coupled mocked tests; migrated actual retained binding callers. Corrected AgentReady constructor to initialize the Textual Message owner.
- Production bootstrap test142319c deletes all manual schema installs, with actual installed complete native path passing; parent may consume this scoped checkpoint independently.
- Pins merged core280487ebb9ec4468a70a92fc172dd5f2f50950a3c87 and Textual8mainc9743801c98dc570f82f82e25915ecce89800f4b; no stale feature pin.

## Exact evidence so far

Installed noneditable wheels, no product PYTHONPATH: native-retired-surface.txt complete Pi/ACP queue, native mapping, cold reattach, DM/channel feedback, stopped reopen passes; active rich surface destroyed and native input queued before replacement, original native editor state restored through actual TextAreaState. No claim of global64 bound from this one-owner test.

native-permission.txt2passed Allow/disconnect; native-permission-retired.txt1passed grant after retirement; native-permission-reject.txt1passed reject after retirement inside real revoke-midturn Pi/MCP/socket case. Closed-event-loop process watcher warning retained. permission-lifetime.txt passes mounted RPC grant/reject/stop/session replacement after real view removal/rebind. Guards3passed; installed navigation2passed. Final combined-head/ratchet verification in progress.

## Tesla integration closure

App/MainScreen still own the old screen-keyed coordination_facts projection. Tesla has explicit contract to delete App.coordination_facts, make MainScreen.coordination_root read actual Agent.coordination, remove second on_coordination_update store, detach before surface retirement, and stop on logical close/shutdown. No edits to these reserved files here. Full global presentation bound is Tesla-owned and not claimed by this PR. Parent owns integration order and live installation.
