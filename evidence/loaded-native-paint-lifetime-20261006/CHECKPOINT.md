# Loaded native paint lifetime

Loaded02 completed four views and reached sixteen. Returning to session-13 failed because a captured body weakref was gone. The recorded cursor, pages, fragment views and visible text checks had already passed. No later cohort is qualified.

`MeasuredViewportBody.finish_native_retirement` commits the original captured `RenderedBody` before removing reconstructible children. `LiveBody.retire` delegates this lifecycle. A live Markdown leaf and its cache therefore have a shorter lifetime than the same committed source fragment and its captured native rows. The old checkpoint applied the leaf lifetime to both.

`ReaderCheckpoint` now captures one declared witness per actual paint resource. Exact warm return still requires the same body and cache/content objects. Only a source-bound live fragment witness can verify its original owner's native retirement: the same fragment/view must remain visible, its ready RenderedBody must own actual native content, and its nonwhite visible crop must equal the original native frame crop. The shared source check still requires the same editor, reader, pages, fragments, fragment views and complete native text.

Loaded returns report native retirements separately. Such a return gets no exact warm-identity credit. Zero additional raw page reads remains mandatory. The original warm-only and genuine-eviction checks are unchanged. Diagnostics already enumerate both live Markdown and measured native bodies.

This changes two acceptance helpers only. Production, pins, frozen operator helpers and retained wheels are untouched. The source relationship does not prove which resource loaded02 originally captured or assign its sole runtime cause. The corrected mounted loaded family remains unqualified until a fresh affected purpose.

Both edited helpers compile without imports; all 400 test modules parse with no omissions. The source and complete checkpoint consumers are recorded in SOURCE-CHECK.json. No test/App/provider/native/package operation was repeated.
