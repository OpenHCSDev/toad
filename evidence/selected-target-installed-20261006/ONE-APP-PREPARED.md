# One installed selected-target App

The existing SDK/ACP batch acceptance now calls the existing selected_target_actions before its original native start/stop checks. One actual App exercises Ctrl/Shift selection, mixed thread/channel read and pins, real partial archive failure, inactive exact-tag removal, native overlapping owner deduplication and only the successfully reopened peer reconnect. All original assertions and standalone modes remain intact. Catalog reads are observed through the existing profile callback and must stay off the UI thread.

Original ToadApp owns joined worker/native-child cleanup. Original native_journey has provider_request_budget=0. No new provider path, application, backend behavior, queue, fallback or fixture class is introduced. Production, pins and wheels are unchanged.

Changed only batch_started_target_actions; all original assertions are ASTequal. Selected package/dependency roots parsed without omissions using the existing audit Package. The changed helper compiles without product imports. Installed acceptance is UNRUN; fresh floor and exact proof/controller tuple remain required before issue.
