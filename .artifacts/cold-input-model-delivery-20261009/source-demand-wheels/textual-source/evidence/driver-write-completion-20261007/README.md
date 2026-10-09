# Driver-owned write completion

Driver.call_after_flush schedules its synchronous callback on the original
Driver App loop after its output flush boundary. Synchronous drivers use their
actual flush; queued Linux and Windows writers use the original WriterThread
FIFO signal. The existing signal now carries and publishes onto that loop.
There is no Toad platform decision or ambient-loop wrapper in this capability.

Headless has no output to wait for. Inline flushes its buffered file. Web waits
for complete framed-packet acceptance at its existing OS write boundary; that
boundary now handles partial os.write results. Neither terminal pixels nor
browser paint are acknowledged. Flush/write failures cannot publish success.

Writer shutdown drains prior signals and clears the original driver's writer
custody; later queued-driver submission is refused outside application mode.
A retired App loop receives no completion. Callback exceptions execute under
the App loop's normal exception handling, not on the terminal writer thread.
WriterThread.call_after_flush now requires the original loop explicitly, and
all native consumers including its original control are migrated.

Qualified native source checks: four focused controls passed in 0.35 seconds,
covering FIFO flush, callback thread/loop, headless scheduling, buffered inline
file flush, closed-loop retirement and joined writer shutdown.

The original WebDriver accepted a 1,100,005-byte framed pipe packet across two
actual OS writes; exact bytes and owner-loop completion passed, and the reader
joined. This proves transport acceptance, not browser paint.

The actual Linux source App rendered through its original writer and delivered
completion on its App loop. Writer and input thread joined. PTY input was used;
output was captured to stderr, not inspected as terminal pixels. The first run
failed only its cleanup oracle: Linux retains the joined input Thread object.
That negative is retained. The corrected Linux-only check passed without
repeating the Web control. Captured stderr includes normal terminal output.

Windows console startup remains unexecuted on this Linux host. Its original
shared WriterThread path is source-reviewed and that writer is exercised above.
No latency improvement is claimed. Native verification used zero inputs and
providers; Parent separately verified and published the paired Linux saved-tab
App. Production remains byte-identical to the delivered 41e8a5319 checkpoint.
