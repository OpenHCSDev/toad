# Deferred watcher ownership

Async watcher results were created by `invoke_watcher`, then hidden in a
`partial(await_watcher, ...)`. Dropping an undelivered callback did not close
the coroutine. A receiver can also be constructed and abandoned before its
message task ever starts; task exit alone cannot cover that lifetime.

`WatcherCallback`, an original Callback subtype, now owns that result's await
and disposal. `Message._discard` supplies the delivery resource hook.
MessagePump releases rejected messages, abandoned callback batches, and pending
messages on task exit or never-started receiver destruction. Actual watcher
invocation stays immediate, arguments retain their original values, and compute
still follows successful completion. Disposing a delivery closes native
coroutines; it does not cancel independently owned Tasks or Futures.

The source pass covered Reactive invocation/reset/subscriptions, Callback
dispatch, Message completion/bubbling/replacement, pump admission/startup/close/
batch cancellation, and the call_next consumers in App, Widget, Screen, Signal,
Lazy, AwaitMount, AwaitRemove and AwaitComplete. No dispatch supply, directory
watcher, Toad caller, or frame publication behavior was replaced.
The existing Package AST reader parsed 250 native modules with no omissions;
the source search found no competing native or current Toad `__del__` owner.

## Verification

- Existing reactive and message-pump checks plus five lifetime checks:
  **46 passed, 1.19s**. These cover immediate synchronous invocation, borrowed
  Task ownership, running/pending watcher cancellation, closed receiver
  rejection, never-mounted DirectoryTree disposal, and real tree removal.
- Original `tests/sidebar_retirement_pilot.py`, unchanged, using the released
  sidebar-eviction author runtime with this native source: **exit 0, empty
  stderr**. All three cycles restored actual selected filenames and scroll
  positions, collected retired panel graphs, and completed source replacement
  and hydration cancellation assertions. No provider inputs or package changes.

Logs: `/home/ts/.cache/agent-scratch/native-watcher-retirement-20261007/`.
`native-final.log`, `app02.stdout.log`, and `app02.stderr.log` are the final
results. `app.stdout.log` / `app.stderr.log` preserve the initial App negative:
restoration passed but the 161-byte unawaited-coroutine warning remained before
never-started receiver disposal was added. An attempted callback-only finalizer
also failed the unmounted-tree check; that competing finalizer was deleted.

This is native source plus affected source-App acceptance. No installed wheel,
live UI, or performance improvement is claimed. The original app fixture owns
its private child cleanup; exact child birth records were not collected here.
