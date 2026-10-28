"""Total UI-thread work per frame and input-to-paint latency in a live Textual app.

``install`` runs inside the application (through ``capture_live.py --frame-meter``).
Every event-loop callback is timed; a frame is the UI-thread work done since the
previous frame was handed to the driver. An input event is timed from the moment
the driver posts it to the App until the first frame handed over after its last
handler returns. ``python frame_meter.py RESULT.json`` prints the series-table numbers.
"""

import bisect
import collections
import json
import os
import statistics
import sys
import threading
import time
from contextlib import contextmanager

# Intervals (monotonic ns) in which a snapshot ran inside the app: the meter
# leaves frames and lags overlapping them out, since the measurement caused them.
PAUSES: list[tuple[int, int]] = []


class CaptureProcessMismatch(RuntimeError):
    """Remote capture entered a process other than the requested application."""


@contextmanager
def measuring_pause():
    begin = time.monotonic_ns()
    try:
        yield
    finally:
        PAUSES.append((begin, time.monotonic_ns()))


def _running_app(expected_pid):
    """The application running in this process (remote code runs outside its context)."""
    from textual.app import App

    if os.getpid() != expected_pid:
        raise CaptureProcessMismatch("Unexpected capture process")
    return App.running_app()


class BoundedCapture:
    """Own admitted JSON bytes, weak identities, timers and reversible hooks.

    The final status has an 8192-byte reservation, including its key/separators.
    Records are encoded ONCE before admission; product objects never enter buffers.
    Hooks are restored before output, even when setup or encoding fails.
    """

    FINAL_RESERVE = 8192
    CONTRACT = 1

    def __init__(self, *, expected_pid, seconds, output, max_records, max_bytes,
                 metadata_only, streams, fields=None):
        import asyncio
        import math
        from pathlib import Path

        if os.getpid() != expected_pid:
            raise CaptureProcessMismatch("Unexpected capture process")
        self.loop = asyncio.get_running_loop()  # MUST precede patches
        if not math.isfinite(seconds) or not 0 < seconds <= 3600:
            raise ValueError("Capture duration must be in (0, 3600]")
        if type(max_records) is not int or not 1 <= max_records <= 1_000_000:
            raise ValueError("Invalid record bound")
        if type(max_bytes) is not int or not self.FINAL_RESERVE + 4096 <= max_bytes <= 128 << 20:
            raise ValueError("Invalid byte bound")
        self.output = Path(output)
        self.partial = self.output.with_name(self.output.name + '.partial')
        if self.output.exists() or self.partial.exists():
            raise FileExistsError("Capture output must be fresh")
        self.max_records, self.max_bytes = max_records, max_bytes
        self.metadata_only = metadata_only
        self.seconds = seconds
        self.started = time.monotonic_ns()
        self.lock = threading.RLock()
        self.accepting, self.finished = True, False
        self.count = self.dropped = self.censored = self.open_spans = 0
        self.cap_exhausted = False
        self.error = None
        self.reason = "explicit"
        self.hooks, self.timers = [], []
        self.probe_timer = None
        self.pending_inputs = {}
        self.identities = {}
        self.next_label = self.next_span = 0
        self.buffers = {name: bytearray() for name in streams}
        self.header = self.encode(dict(pid=expected_pid, seconds=seconds,
                                       metadata_only=metadata_only, **(fields or {})))[:-1]
        self.used = len(self.header) + 1  # final closing brace
        self.used += sum(len(self.encode(name)) + 4 for name in self.buffers)  # ,key:[]
        if self.used + self.FINAL_RESERVE > max_bytes:
            raise ValueError("Envelope exceeds capture bound")

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')

    def record(self, stream, value):
        with self.lock:
            if not self.accepting:
                return False
            try:
                data = self.encode(value)
                buffer = self.buffers[stream]
                size = len(data) + bool(buffer)
                if self.count >= self.max_records or self.used + size + self.FINAL_RESERVE > self.max_bytes:
                    self.dropped += 1
                    self.cap_exhausted = True
                    self.stop('cap')
                    return False
                if buffer:
                    buffer.extend(b',')
                buffer.extend(data)
                self.used += size
                self.count += 1
                if self.count == self.max_records:
                    self.cap_exhausted = True
                    self.stop('cap')
                return True
            except Exception as error:
                self.error = type(error).__name__[:96]
                self.stop('recording-error')
                return False

    def stop(self, reason):
        """Stop admission immediately; restoration runs on the owning loop."""
        self.accepting = False
        self.reason = reason
        self.loop.call_soon_threadsafe(self.finish, reason)

    def label(self, value):
        """Never retain or hash a product object, and never confuse reused ids."""
        import weakref

        if value is None:
            return None
        with self.lock:
            if not self.accepting:
                return None
            key = id(value)
            previous = self.identities.get(key)
            if previous is not None and previous[0]() is value:
                return previous[1]
            if len(self.identities) >= self.max_records:
                self.cap_exhausted = True
                self.stop('identity-cap')
                return None
            self.next_label += 1
            label = self.next_label

            def retired(reference):
                with self.lock:
                    found = self.identities.get(key)
                    if found is not None and found[0] is reference:
                        del self.identities[key]
                        self.record('events', dict(event='retired', label=label, at_ns=time.monotonic_ns()))
            try:
                reference = weakref.ref(value, retired)
            except TypeError:
                return None  # explicitly unsupported lifetime, never bare id()
            self.identities[key] = reference, label
            self.record('events', dict(event='identity', label=label, type=_type_name(value),
                                       at_ns=time.monotonic_ns()))
            return label

    def patch(self, target, wrapper):
        """Targets have all been resolved and validated before the first patch."""
        target.install(self, wrapper)

    def arm(self):
        self.timers.append(self.loop.call_later(self.seconds, self.finish, 'duration'))
        return self.finish

    def finish(self, reason='explicit'):
        import inspect

        with self.lock:
            if self.finished:
                return self.status
            self.accepting, self.finished = False, True
            self.reason = reason
            if (probe_timer := self.probe_timer) is not None:
                probe_timer.cancel()
                self.probe_timer = None
            for timer in self.timers:
                timer.cancel()
            self.timers.clear()
            restored = skipped = failed = 0
            for owner, name, original, installed, inherited in reversed(self.hooks):
                try:
                    if inspect.getattr_static(owner, name) is installed:
                        if inherited:
                            delattr(owner, name)
                        else:
                            setattr(owner, name, original)
                        restored += 1
                    else:
                        skipped += 1
                except Exception:
                    failed += 1
            self.hooks.clear()
            self.identities.clear()
            pending_inputs = len(self.pending_inputs)
            self.pending_inputs.clear()
            self.status = dict(contract=self.CONTRACT, reason=reason,
                               started_ns=self.started, ended_ns=time.monotonic_ns(),
                               measured_records=self.count, dropped_records=self.dropped,
                               censored_spans=self.open_spans + self.censored,
                               censored_inputs=pending_inputs,
                               cap_exhausted=self.cap_exhausted, error=self.error,
                               hooks_restored=restored, hooks_superseded=skipped,
                               hooks_failed=failed, cleanup=('failed' if failed else
                                                            'superseded' if skipped else 'restored'),
                               max_records=self.max_records, max_bytes=self.max_bytes,
                               output_bytes=0, pixels_observed=False)
            # The count includes its own decimal spelling: settle to a fixed point.
            footer = b',"capture":' + self.encode(self.status)
            for _ in range(8):
                self.status['output_bytes'] = self.used + len(footer)
                updated = b',"capture":' + self.encode(self.status)
                if updated == footer:
                    break
                footer = updated
            if len(footer) > self.FINAL_RESERVE:
                raise RuntimeError('Final status exceeded reserved envelope')
            try:
                fd = os.open(self.partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as file:
                    file.write(self.header)
                    for name, buffer in self.buffers.items():
                        file.write(b',' + self.encode(name) + b':[')
                        file.write(buffer)
                        file.write(b']')
                    file.write(footer + b'}')
                os.rename(self.partial, self.output)
            finally:
                self.buffers.clear()
            return self.status


class MethodTarget:
    """The exact descriptor declaration and binding needed for one hook."""

    def __init__(self, path):
        import importlib
        import inspect

        module, separator, attribute = path.partition(':')
        if not separator or len(path) > 240:
            raise ValueError('Invalid capture target')
        owner = importlib.import_module(module)
        *parents, self.name = attribute.split('.')
        for parent in parents:
            owner = getattr(owner, parent)
        self.owner, self.path = owner, path
        self.declared = inspect.getattr_static(owner, self.name)
        self.inherited = self.name not in vars(owner)
        self.bind = type(self.declared) if isinstance(self.declared, (classmethod, staticmethod)) else lambda value: value
        self.original = self.declared.__func__ if isinstance(self.declared, (classmethod, staticmethod)) else self.declared
        if not inspect.isfunction(self.original):
            raise TypeError('Capture target must be a Python function descriptor')
        if getattr(self.original, '_bounded_capture', False):
            raise RuntimeError('Target already belongs to a capture')
        self.asynchronous = inspect.iscoroutinefunction(self.original)
        self.signature = inspect.signature(self.original)

    def install(self, capture, wrapper):
        wrapper._bounded_capture = True
        installed = self.bind(wrapper)
        # Record before assignment so even a raising descriptor setup is reversible.
        capture.hooks.append((self.owner, self.name, self.declared, installed, self.inherited))
        setattr(self.owner, self.name, installed)


def _type_name(value):
    return (type(value).__module__ + '.' + type(value).__qualname__)[:160]


def _cursor_metadata(cursor):
    # TranscriptCursor declares these defaults on the base; no family redispatch.
    if cursor is None:
        return None
    return dict(type=_type_name(cursor), session_file=(cursor.session_file or '')[:384],
                offset=cursor.offset, wire_sequence=cursor.wire.sequence)


def _page_metadata(capture, prepared):
    page = prepared.page
    witness = page.snapshot
    return dict(prepared=capture.label(prepared), before=_cursor_metadata(page.before),
                after=_cursor_metadata(page.after), fragments=len(prepared.fragments),
                root=witness.root[:384], thread=witness.requested_name[:160],
                through=_cursor_metadata(witness.through),
                thread_birth=witness.thread.incarnation.wire_birth,
                snapshot=capture.label(witness), no_match=not prepared.fragments)


class CallMetadata:
    """Typed observation adapters; product algorithms and keys remain untouched."""

    targets = {}
    path = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.path is not None:
            cls.targets[cls.path] = cls()

    def enter(self, capture, arguments):
        return {}

    def result(self, capture, result):
        return dict(result_type=_type_name(result))


class SourceGetMetadata(CallMetadata):
    path = 'toad.transcript_preparation:PreparedPageSource.get'

    def enter(self, capture, arguments):
        source, request = arguments['self'], arguments['request']
        return dict(source=capture.label(source), scope=capture.label(source.scope),
                    direction=_type_name(request.end), cursor=_cursor_metadata(request.cursor))

    def result(self, capture, result):
        return _page_metadata(capture, result)


class RowsMetadata(CallMetadata):
    path = 'toad.transcript_preparation:PreparedTranscriptPage.prepare_rows'

    def enter(self, capture, arguments):
        view, prepared = arguments['view'], arguments['self']
        return dict(**_page_metadata(capture, prepared), history=capture.label(view),
                    width=arguments['target'].line_width, direction=_type_name(arguments['end']),
                    filter=capture.label(arguments['selected']), rows_needed=arguments['rows_needed'])


class LoadMetadata(CallMetadata):
    path = 'toad.widgets.transcript_history:LineHistory._load_page'

    def enter(self, capture, arguments):
        history = arguments['self']
        return dict(history=capture.label(history), source=capture.label(history.page_source),
                    scope=capture.label(history.page_source.scope), width=history.line_width,
                    filter=capture.label(history.filter), direction=_type_name(arguments['end']))


class ExtendMetadata(CallMetadata):
    path = 'toad.widgets.transcript_history:LineHistory._extend_and_trim'

    def enter(self, capture, arguments):
        return dict(**_page_metadata(capture, arguments['prepared']), history=capture.label(arguments['self']),
                    direction=_type_name(arguments['end']), local=arguments['local'])


class PublishedMetadata(CallMetadata):
    path = 'toad.transcript_source_preparation:TranscriptSourcePreparation.rows_published'

    def enter(self, capture, arguments):
        return dict(history=capture.label(arguments['self']),
                    meaning='rows-admitted-not-layout-or-pixels')


class SelectedMetadata(CallMetadata):
    path = 'toad.app:ToadApp.select_session'

    def enter(self, capture, arguments):
        return dict(mode=arguments['mode'][:160])


class SwitchingMetadata(SelectedMetadata):
    path = 'toad.app:ToadApp._switch_mode_ready'


class ToastMetadata(CallMetadata):
    path = 'toad.widgets.switch_toast:SwitchToast.show'


class WriterMetadata(CallMetadata):
    path = 'textual.drivers._writer_thread:_FlushSignal.deliver'

    def enter(self, capture, arguments):
        return dict(signal=capture.label(arguments['self']), meaning='writer-flushed-not-pixels')


class WrittenMetadata(CallMetadata):
    path = 'toad.frame_presentation:FramePresentation.written'

    def enter(self, capture, arguments):
        return dict(frame=capture.label(arguments['self']), scene=capture.label(arguments['writing']),
                    meaning='writer-acknowledgement-on-ui-loop-not-pixels')


def install(*, expected_pid, seconds, output, max_records=20000, max_bytes=3 << 20,
            metadata_only=False):
    """Bound total loop work and actual display handoffs, without a heap sampler.

    frames/inputs/lags retain the shapes consumed by summarize(). Diagnostic
    events are flat records, not growing callback/stack dictionaries.
    """
    import asyncio
    from textual import events

    app = _running_app(expected_pid)
    paths = ('asyncio.events:Handle._run',
             'textual.message_pump:MessagePump.post_message',
             'textual.message_pump:MessagePump._dispatch_message',
             'textual.widget:Widget.refresh', 'textual.widget:Widget._request_layout',
             'textual.screen:Screen.refresh_bindings', 'textual.screen:Screen._refresh_layout',
             'textual.screen:Screen._layout_step')
    targets = [MethodTarget(path) for path in paths]
    display_target = MethodTarget('toad.app:ToadApp._display')
    targets.append(display_target)
    capture = BoundedCapture(expected_pid=expected_pid, seconds=seconds, output=output,
                             max_records=max_records, max_bytes=max_bytes, metadata_only=metadata_only,
                             streams=('frames', 'inputs', 'lags', 'events', 'switch_steps', 'stepped_layouts',
                                      'slow_frames', 'timed_callbacks', 'slow_handlers', 'layout_invalidations'))
    run, post, dispatch, refresh, request_layout, refresh_bindings, refresh_layout, layout_step, display = (
        target.original for target in targets)
    inputs_types = (events.Key, events.MouseEvent)
    clock = time.monotonic_ns
    state = dict(busy=0, current=None, cpu=time.thread_time_ns(), shown=clock(),
                 stretch_begin=clock(), stretch_end=clock(), stall=0, layout=0, layouts=0)

    def counted_layout(self, required=True):
        if required:
            capture.record('layout_invalidations', dict(at_ns=clock(), widget=_type_name(self)))
        return request_layout(self, required)

    def counted_refresh(self, *regions, repaint=True, layout=False, recompose=False):
        capture.record('events', dict(event='refresh', at_ns=clock(), widget=_type_name(self),
                                      repaint=repaint, layout=layout, recompose=recompose))
        return refresh(self, *regions, repaint=repaint, layout=layout, recompose=recompose)

    def traced_layout_step(self, steps, deadline, step_ns):
        begin = clock()
        try:
            return layout_step(self, steps, deadline, step_ns)
        finally:
            capture.record('stepped_layouts', (begin, step_ns, [(clock() - begin) / 1e6]))

    def timed_layout(self, *args, **kwargs):
        begin = clock()
        try:
            return refresh_layout(self, *args, **kwargs)
        finally:
            elapsed = clock() - begin
            state['layout'] += elapsed / 1e6
            state['layouts'] += 1
            capture.record('events', dict(event='layout', start_ns=begin, end_ns=clock(),
                                          screen=capture.label(self)))

    def counted_bindings(self):
        capture.record('events', dict(event='bindings', at_ns=clock()))
        return refresh_bindings(self)

    def timed_run(handle):
        if not capture.accepting:
            return run(handle)
        state['current'] = begin = clock()
        cpu_begin = time.thread_time_ns()
        if begin - state['stretch_end'] > 1_000_000:
            state['stretch_begin'] = begin
        try:
            return run(handle)
        finally:
            end = clock()
            state['stretch_end'] = end
            state['stall'] = max(state['stall'], (end - state['stretch_begin']) / 1e6)
            state['busy'] += end - begin
            state['current'] = None
            if end - begin > 8_000_000:
                capture.record('timed_callbacks', (begin, (end - begin) / 1e6,
                                                   _type_name(handle._callback),
                                                   (time.thread_time_ns() - cpu_begin) / 1e6))

    def timed_display(self, screen, renderable):
        result = display(self, screen, renderable)
        if capture.accepting and renderable is not None and self is app:
            now = clock()
            running = 0 if state["current"] is None else now - state["current"]
            work = (state["busy"] + running) / 1e6
            cpu = time.thread_time_ns()
            capture.record('frames', (now, work, state['stall']))
            capture.record('events', dict(event='display-handoff', at_ns=now,
                                          screen=capture.label(screen), pixels_observed=False))
            # A paint ends the stretch: the next one starts after it.
            state["stall"] = 0
            state["stretch_begin"] = state["stretch_end"] = now
            if work > 16:
                # UI-thread CPU over the same interval: far below the work
                # means the loop was waiting for the GIL, not computing.
                capture.record('slow_frames', (now, work, [], (cpu - state['cpu']) / 1e6,
                                                (now - state['shown']) / 1e6,
                                                state['layout'], state['layouts']))
            state["cpu"], state["shown"] = cpu, now
            state["layout"] = state["layouts"] = 0
            # The running callback adds its full duration when it returns;
            # the part already counted in this frame is subtracted here.
            state["busy"] = -running
        return result

    # Weak labels plus scalar start times, never retained messages or nested handler lists.
    posted = capture.pending_inputs

    def timed_post(self, message):
        if capture.accepting and self is app and isinstance(message, inputs_types):
            label = capture.label(message)
            if label is not None:
                posted.setdefault(label, (clock(), type(message).__name__[:160]))
        return post(self, message)

    async def timed_dispatch(self, message):
        begin = clock()
        try:
            return await dispatch(self, message)
        finally:
            if capture.accepting and self is app and isinstance(message, inputs_types):
                label = capture.label(message)
                if (entry := posted.pop(label, None)) is not None:
                    capture.record('inputs', (entry[0], clock(), entry[1], []))
                if clock() - begin > 50_000_000:
                    capture.record('slow_handlers', (begin, (clock() - begin) / 1e6,
                                                     _type_name(self), _type_name(message)))

    loop = capture.loop
    probe_timer = None

    def probe(due):
        nonlocal probe_timer
        if not capture.accepting:
            return
        now = loop.time()
        capture.record('lags', (clock(), round((now - due) * 1000, 2)))
        if capture.accepting:
            probe_timer = loop.call_at(now + 0.004, probe, now + 0.004)
            # Only the current probe is retained; no growing timer roster.
            capture.probe_timer = probe_timer

    try:
        wrappers = (timed_run, timed_post, timed_dispatch, counted_refresh, counted_layout,
                    counted_bindings, timed_layout, traced_layout_step, timed_display)
        for target, wrapper in zip(targets, wrappers, strict=True):
            capture.patch(target, wrapper)
        probe_timer = loop.call_at(loop.time() + 0.004, probe, loop.time() + 0.004)
        capture.probe_timer = probe_timer
        return capture.arm()
    except BaseException:
        capture.finish('setup-error')
        raise


def targets(*, expected_pid, output):
    """Write where sidebar thread rows and session tabs are, in screen cells."""
    with measuring_pause():
        _targets(expected_pid=expected_pid, output=output)


def _targets(*, expected_pid, output):
    app = _running_app(expected_pid)
    from toad.widgets.history_anchor import HistoryWindow

    screen = app.screen
    # Only on-screen rows and tabs can be clicked; reading an off-screen
    # widget's region would make the app reflow its viewport.
    shown = screen._compositor.visible_widgets
    rows = {row.target_name: tuple(shown[row][0]) for row in screen.query("ThreadRow") if row in shown}
    tabs = [tuple(shown[tab][0]) for tab in screen.query("SessionLabel") if tab in shown]
    # What the screen actually shows, row by row, and the visible message
    # window: the scenario checks blank runs, placeholders, End and tab return
    # from this text rather than from screenshots.
    compositor = screen._compositor
    text = [strip.text for strip in compositor.render_strips()]
    visible = compositor.visible_widgets
    window = next((node for node in screen.query(HistoryWindow) if node in visible), None)
    message_window = None
    if window is not None:
        region = window.scrollable_content_region
        message_window = {"region": tuple(region), "scroll_y": window.scroll_y,
                          "max_scroll_y": window.max_scroll_y, "follows_tail": window.follows_tail}
    # Readers wait for the path to exist, so it appears only once complete.
    partial = f"{output}.partial"
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        arranged = {}
        for node in compositor._layout_map:
            arranged[type(node).__name__] = arranged.get(type(node).__name__, 0) + 1
        # What each open tab keeps warm, as the retention budget counts it.
        retained = [{"screen": screen_.id, "widgets": owner.retained_widget_count,
                     "source_bytes": owner.retained_source_bytes, "paint_bytes": owner.retained_paint_bytes}
                    for screen_, owner in app.workspace_chrome.native._presentations()]
        # Everything the current conversation mounted, shown or not, by type.
        mounted = collections.Counter(
            type(node).__name__ for view in app.workspace_sessions.views.values()
            if (owner := getattr(view, "presentation", None)) is not None and owner.widget is not None
            for node in owner.widget.walk_children(with_self=True))
        json.dump({"threads": rows, "tabs": tabs, "text": text, "message_window": message_window,
                   "arranged": arranged, "retained": retained, "mounted": dict(mounted.most_common())}, file)
    os.link(partial, output)  # fails, like the exclusive create did, if output exists
    os.unlink(partial)


def profile_layout(*, expected_pid, output, calls=40, target="textual.screen:Screen._refresh_layout"):
    """Deterministically profile the next calls of ``target`` (sync) and write the top costs.

    cProfile in Python 3.12+ instruments every thread, so background threads'
    work in the same window appears too; read callers before trusting a line.
    """
    import cProfile
    import importlib
    import inspect
    import pstats
    import io

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    module_name, _, path = target.partition(":")
    Screen = importlib.import_module(module_name)
    *parents, method = path.split(".")
    for parent in parents:
        Screen = getattr(Screen, parent)
    original = getattr(Screen, method)
    profiler = cProfile.Profile()
    seen = {"calls": 0}

    def write():
        if seen["calls"] == calls:
            setattr(Screen, method, original)
        text = io.StringIO()
        stats = pstats.Stats(profiler, stream=text)
        stats.sort_stats("cumulative").print_stats(45)
        stats.sort_stats("tottime").print_stats(30)
        # Comms reads must not run inside a layout: show who calls them.
        stats.print_callers("locked_store|store_files|registration|history_views")
        # Restyling a subtree and mounting are the costs of building a view: who asks.
        stats.print_callers("dom.py.*(add_class|remove_class|set_class)|widget.py.*\\(mount\\)|update_node_styles")
        # The raw statistics, for reading callers offline with pstats.
        profiler.dump_stats(output + ".prof")
        partial = output + ".partial"
        with open(partial, "w") as file:
            file.write(text.getvalue())
        os.rename(partial, output)

    if inspect.iscoroutinefunction(original):
        async def profiled(self, *args, **kwargs):
            if seen["calls"] >= calls:
                return await original(self, *args, **kwargs)
            seen["calls"] += 1
            profiler.enable()
            try:
                return await original(self, *args, **kwargs)
            finally:
                profiler.disable()
                # Cumulative so far: a run with fewer calls still reports.
                write()
    else:
        def profiled(self, *args, **kwargs):
            if seen["calls"] >= calls:
                return original(self, *args, **kwargs)
            seen["calls"] += 1
            profiler.enable()
            try:
                return original(self, *args, **kwargs)
            finally:
                profiler.disable()
                # Cumulative so far: a run with fewer calls still reports.
                write()

    setattr(Screen, method, profiled)


def profile_within(*, expected_pid, output, target, within, calls=3, min_ms=0.0):
    """Profile each call of ``target`` (sync) made while a ``within`` call runs.

    One statistics file per ``within`` call (output.N.prof). With ``min_ms``,
    a ``within`` call is kept only when one of its profiled ``target`` calls
    took at least that long (profiled time), so N counts only slow calls. cProfile sees every
    thread, so while a target call runs the GIL switch interval is raised to
    one second: the target is synchronous Python, so no other thread runs
    inside it and the statistics are the UI thread's alone.
    """
    import cProfile
    import gc
    import importlib
    import inspect

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")

    def resolve(path):
        module_name, _, attribute = path.partition(":")
        owner = importlib.import_module(module_name)
        *parents, method = attribute.split(".")
        for parent in parents:
            owner = getattr(owner, parent)
        return owner, method, getattr(owner, method)

    target_owner, target_name, target_original = resolve(target)
    within_owner, within_name, within_original = resolve(within)
    state = {"current": None, "count": 0, "longest": 0.0, "kept": []}

    def profiled(*args, **kwargs):
        profiler = state["current"]
        if profiler is None:
            return target_original(*args, **kwargs)
        interval = sys.getswitchinterval()
        sys.setswitchinterval(1.0)
        # A collection inside the call is charged to whichever function it
        # interrupts; collection pauses are measured by the frame meter.
        collecting = gc.isenabled()
        gc.disable()
        begin = time.perf_counter()
        try:
            return profiler.runcall(target_original, *args, **kwargs)
        finally:
            state["longest"] = max(state["longest"], (time.perf_counter() - begin) * 1e3)
            if collecting:
                gc.enable()
            sys.setswitchinterval(interval)

    def finish(profiler):
        state["current"] = None
        longest, state["longest"] = state["longest"], 0.0
        if longest < min_ms or (min_ms and not longest):
            return
        state["kept"].append((longest, time.monotonic_ns()))
        state["count"] += 1
        profiler.dump_stats(f"{output}.{state['count']}.prof")
        if state["count"] >= calls:
            setattr(target_owner, target_name, target_original)
            setattr(within_owner, within_name, within_original)
            with open(output, "w") as file:
                json.dump({"profiles": state["count"], "profiled_ms": state["kept"]}, file)

    if inspect.iscoroutinefunction(within_original):
        async def scope(*args, **kwargs):
            if state["count"] >= calls:
                return await within_original(*args, **kwargs)
            profiler = state["current"] = cProfile.Profile()
            try:
                return await within_original(*args, **kwargs)
            finally:
                finish(profiler)
    else:
        def scope(*args, **kwargs):
            if state["count"] >= calls:
                return within_original(*args, **kwargs)
            profiler = state["current"] = cProfile.Profile()
            try:
                return within_original(*args, **kwargs)
            finally:
                finish(profiler)

    setattr(target_owner, target_name, profiled)
    setattr(within_owner, within_name, scope)


def profile_slow(*, expected_pid, output, target, calls=3, min_ms=0.0):
    """Profile every call of ``target`` (sync); keep each one that took ``min_ms`` or longer.

    One statistics file per kept call (output.N.prof), at most ``calls``. For
    a target with no patchable enclosing call (the screen's update timer holds
    a bound method, so ``profile_within`` cannot scope its layout). Other
    threads are kept off the GIL during each call, as in ``profile_within``.
    """
    import cProfile
    import gc
    import importlib

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    module_name, _, attribute = target.partition(":")
    owner = importlib.import_module(module_name)
    *parents, name = attribute.split(".")
    for parent in parents:
        owner = getattr(owner, parent)
    original = getattr(owner, name)
    kept = []
    running = []

    def profiled(*args, **kwargs):
        if running:
            # A nested call (arrange measures by arranging) is part of the outer profile.
            return original(*args, **kwargs)
        running.append(True)
        try:
            return profile_call(*args, **kwargs)
        finally:
            running.pop()

    def profile_call(*args, **kwargs):
        profiler = cProfile.Profile()
        interval = sys.getswitchinterval()
        sys.setswitchinterval(1.0)
        collecting = gc.isenabled()
        gc.disable()
        begin = time.perf_counter()
        try:
            return profiler.runcall(original, *args, **kwargs)
        finally:
            spent = (time.perf_counter() - begin) * 1e3
            if collecting:
                gc.enable()
            sys.setswitchinterval(interval)
            if spent >= min_ms and len(kept) < calls:
                kept.append((spent, time.monotonic_ns()))
                profiler.dump_stats(f"{output}.{len(kept)}.prof")
                if len(kept) == calls:
                    setattr(owner, name, original)
                    with open(output, "w") as file:
                        json.dump({"profiles": len(kept), "profiled_ms": kept}, file)

    setattr(owner, name, profiled)


def remeasure(*, expected_pid, output, iterations=60):
    """Arrange the live screen at widths it was never laid out at, repeatedly.

    This is the layout work of the first tab switch after the content width
    changes: every widget of the selected tab measured and placed at a new
    width. Each pass arranges the whole screen at a different width (40
    widths in turn, more than a widget's 16 retained measurements), in its
    own loop turn with the collector off, and publishes nothing. The median
    is a per-build figure for the real widget tree, free of the switch's
    other work and of collector pauses. A second set of passes is profiled
    with other threads kept off the GIL, for call counts.

    Measurement caches gain entries for widths the screen is not shown at,
    and transcript pages re-wrap at them: run this after the scenario's checks.
    """
    import asyncio
    import contextvars
    import cProfile
    import gc
    from textual._context import active_app
    from textual.geometry import Size

    app = _running_app(expected_pid)
    # Remote code runs outside the app's context; measurement reads it.
    context = contextvars.copy_context()
    context.run(active_app.set, app)
    screen = app.screen
    width, height = app.size
    passes: list[tuple[int, float, float]] = []
    profiler = cProfile.Profile()
    loop = asyncio.get_running_loop()

    def arrange(index: int, profiled: bool) -> None:
        size = Size(width - 5 - index % 40, height)
        enabled = gc.isenabled()
        gc.disable()
        interval = sys.getswitchinterval()
        if profiled:
            sys.setswitchinterval(1.0)
            profiler.enable()
        begin, cpu = time.perf_counter_ns(), time.thread_time_ns()
        try:
            screen._compositor._arrange_root(screen, size)
        finally:
            spent, spent_cpu = time.perf_counter_ns() - begin, time.thread_time_ns() - cpu
            if profiled:
                profiler.disable()
                sys.setswitchinterval(interval)
            if enabled:
                gc.enable()
        if not profiled:
            passes.append((size.width, spent / 1e6, spent_cpu / 1e6))

    def step(index: int) -> None:
        if index < 2 * iterations:
            # Timed passes first, then the same widths again profiled.
            try:
                arrange(index % iterations, profiled=index >= iterations)
            except Exception:
                # A loop callback's exception is only logged inside the app:
                # write it where the capture waits for the result.
                import traceback
                with open(output, "w") as file:
                    json.dump({"error": traceback.format_exc()}, file)
                raise
            loop.call_later(0.01, step, index + 1, context=context)
            return
        profiler.dump_stats(output + ".prof")
        times = sorted(ms for _width, ms, _cpu in passes)
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump({"passes": passes, "median_ms": statistics.median(times),
                       "p10_ms": times[len(times) // 10], "p90_ms": times[len(times) * 9 // 10],
                       "unit_costs": costs, "profiled_passes": iterations}, file)
        os.rename(partial, output)

    def unit_costs() -> dict[str, float]:
        # Per-operation costs in this process, to compare with a fresh one:
        # the deepest widget's parent walk and two attribute reads.
        deepest = max(screen.walk_children(), key=lambda widget: len(tuple(widget.walk_ancestors())))
        costs = {"depth": len(tuple(deepest.walk_ancestors()))}
        for label, operation in (("walk_ancestors_ns", lambda: tuple(deepest.walk_ancestors())),
                                 ("parent_ns", lambda: deepest._parent),
                                 ("styles_height_ns", lambda: deepest.styles.height)):
            begin = time.perf_counter_ns()
            for _ in range(2000):
                operation()
            costs[label] = (time.perf_counter_ns() - begin) / 2000
        return costs

    costs = context.run(unit_costs)
    loop.call_soon(step, 0, context=context)


def repaint(*, expected_pid, output, iterations=40):
    """Repaint the live history viewport in full, repeatedly, and time each paint.

    The paint of a PageUp into history not shown before: every widget drawn
    inside the history window renders its lines again (their styled-line
    caches are cleared) and the window's whole viewport is damaged, then the
    screen publishes it through the real driver. "warm" passes damage the
    same viewport without clearing the line caches (the paint of rows shown
    before). "scroll" passes move the window a page up, then back down, and
    run the screen update the update timer would run (layout, then paint):
    a PageUp's frame within history already loaded. Each pass runs in its own
    loop turn with the collector off; then cold and scroll passes again,
    profiled with other threads kept off the GIL (repaint.json.prof holds
    the cold ones, repaint.json.scroll.prof the scroll ones).
    Run after the scenario's checks: the passes write to the terminal.
    """
    import asyncio
    import contextvars
    import cProfile
    import gc
    from textual._compositor import ChopsUpdate, Compositor
    from textual._context import active_app
    from toad.widgets.history_anchor import HistoryWindow

    app = _running_app(expected_pid)
    context = contextvars.copy_context()
    context.run(active_app.set, app)
    screen = app.screen
    compositor = screen._compositor
    windows = [window for window in screen.query(HistoryWindow) if window in compositor.visible_widgets]
    if len(windows) != 1:
        raise RuntimeError(f"Expected one visible history window, found {len(windows)}")
    window = windows[0]
    passes: list[dict] = []
    profilers = {"cold": cProfile.Profile(), "scroll": cProfile.Profile()}
    loop = asyncio.get_running_loop()
    parts: dict[str, float] = {}
    described: list[dict] = []
    from textual.screen import Screen

    def timed_part(name, original):
        def timed(*args, **kwargs):
            begin = time.perf_counter_ns()
            try:
                return original(*args, **kwargs)
            finally:
                parts[name] = parts.get(name, 0.0) + (time.perf_counter_ns() - begin) / 1e6
        return timed

    def paint(kind: str, profiled: bool, index: int) -> None:
        clip = compositor.visible_widgets[window][1]
        drawn = [widget for widget, (_region, widget_clip) in compositor.visible_widgets.items()
                 if widget_clip.overlaps(clip) and (widget is window or window in widget.ancestors)]
        if kind == "cold":
            for widget in drawn:
                widget._styles_cache.clear()
        if kind == "scroll":
            # Up a page on even passes, back down on odd ones: loaded history.
            page = window.scrollable_content_region.height
            window.scroll_to(y=window.scroll_y + (page if index % 2 else -page), animate=False, immediate=True)
            # What the window's idle check and the screen's UpdateScroll
            # handler do, so this turn's update lays out the scroll.
            window._check_refresh()
            screen._scroll_required = True
            update = screen._on_timer_update
        else:
            compositor._dirty_regions.add(clip)
            update = screen._compositor_refresh
        written = []
        driver_write = app._driver.write
        app._driver.write = lambda data: (written.append(len(data)), driver_write(data))[1]
        originals = {"partial": Compositor.render_partial_update, "segments": ChopsUpdate.render_segments,
                     "chops": Compositor._render_chops, "layout": Screen._refresh_layout}
        Compositor.render_partial_update = timed_part("partial", originals["partial"])
        ChopsUpdate.render_segments = timed_part("segments", originals["segments"])
        Compositor._render_chops = timed_part("chops", originals["chops"])
        Screen._refresh_layout = timed_part("layout", originals["layout"])
        parts.clear()
        enabled = gc.isenabled()
        gc.disable()
        interval = sys.getswitchinterval()
        profiler = profilers.get(kind)
        if profiled:
            sys.setswitchinterval(1.0)
            profiler.enable()
        begin, cpu = time.perf_counter_ns(), time.thread_time_ns()
        try:
            update()
        finally:
            spent, spent_cpu = time.perf_counter_ns() - begin, time.thread_time_ns() - cpu
            if profiled:
                profiler.disable()
                sys.setswitchinterval(interval)
            if enabled:
                gc.enable()
            Compositor.render_partial_update = originals["partial"]
            ChopsUpdate.render_segments = originals["segments"]
            Compositor._render_chops = originals["chops"]
            Screen._refresh_layout = originals["layout"]
            app._driver.write = driver_write
        if not described:
            # What the viewport is drawn from: each widget's place and the
            # styles its lines are painted with.
            for widget in drawn:
                region, widget_clip = compositor.visible_widgets[widget]
                styles = widget.styles
                described.append({"widget": type(widget).__name__, "region": tuple(region), "clip": tuple(widget_clip),
                                  "padding": tuple(styles.padding), "border": any(edge for edge, _ in styles.border),
                                  "outline": any(edge for edge, _ in styles.outline), "tint": styles.tint.a,
                                  "opacity": widget.opacity, "text_opacity": styles.text_opacity,
                                  "background": str(styles.background), "filters": len(widget.get_line_filters())})
        if not profiled:
            passes.append({"kind": kind, "ms": spent / 1e6, "cpu_ms": spent_cpu / 1e6, "widgets": len(drawn),
                           "rows": clip.height, "columns": clip.width, "bytes": sum(written), **parts})

    schedule = [(kind, False) for kind in ("cold", "warm", "scroll") for _ in range(iterations)]
    schedule += [(kind, True) for kind in ("cold", "scroll") for _ in range(iterations)]

    def step(index: int) -> None:
        if index < len(schedule):
            try:
                paint(*schedule[index], index)
            except Exception:
                import traceback
                with open(output, "w") as file:
                    json.dump({"error": traceback.format_exc()}, file)
                raise
            loop.call_later(0.02, step, index + 1, context=context)
            return
        profilers["cold"].dump_stats(output + ".prof")
        profilers["scroll"].dump_stats(output + ".scroll.prof")

        def summary(kind):
            chosen = [entry for entry in passes if entry["kind"] == kind]
            return {key: round(statistics.median(entry.get(key, 0.0) for entry in chosen), 3)
                    for key in ("ms", "cpu_ms", "layout", "partial", "chops", "segments", "bytes",
                                "widgets", "rows", "columns")}
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump({"cold": summary("cold"), "warm": summary("warm"), "scroll": summary("scroll"),
                       "drawn": described, "passes": passes}, file, indent=1)
        os.rename(partial, output)

    loop.call_soon(step, 0, context=context)


def _subject(args) -> str:
    """Which object a traced call was for (its type and id), and who called it."""
    caller, chain = sys._getframe(2), []
    while caller is not None and len(chain) < 8:
        chain.append(f"{caller.f_code.co_qualname}:{caller.f_lineno}")
        caller = caller.f_back
    from textual.geometry import Region, Size

    # Geometry arguments are shown by value: they tell two measurements of
    # the same widget apart. Any other tuple is named by type: printing a
    # large argument costs the traced thread more than the call did.
    def geometry(subject):
        return isinstance(subject, (Size, Region)) or (
            isinstance(subject, tuple) and all(isinstance(item, (int, float)) for item in subject))

    subjects = " ".join(repr(subject) if geometry(subject)
                        else f"{type(subject).__name__}#{getattr(subject, 'id', None) or ''}"
                        for subject in args[:3])
    return f"{subjects} <- {' < '.join(chain)}"


def _result(value) -> str:
    """A short description of what a traced call returned."""
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return f"{type(value).__name__}[{', '.join(type(item).__name__ for item in value)}]"
    fields = getattr(value, "__dataclass_fields__", None)
    if fields:
        shown = ", ".join(f"{field}={_field(getattr(value, field))}" for field in fields if field != "admissions")
        return f"{type(value).__name__}({shown})"
    return type(value).__name__


def _field(value) -> str:
    """One field of a traced result. A container is counted, not printed:
    printing a large one costs the traced thread more than the call did."""
    if isinstance(value, (dict, list, tuple, set, frozenset)):
        return f"{type(value).__name__}[{len(value)}]"
    return f"{value!r:.40}"


class CallSpan:
    """One scalar-only span. Context carries ids, never a task, page or widget."""

    def __init__(self, capture, target, metadata, parent, args, kwargs):
        self.capture, self.target, self.metadata, self.parent = capture, target, metadata, parent
        self.start, self.cpu = time.monotonic_ns(), time.thread_time_ns()
        with capture.lock:
            capture.next_span += 1
            self.identity = capture.next_span
            capture.open_spans += 1
        self.token = parent.set(self.identity)
        try:
            arguments = target.signature.bind(*args, **kwargs).arguments
            fields = metadata.enter(capture, arguments)
            capture.record('calls', dict(event='enter', span=self.identity, parent=self.token.old_value
                                         if type(self.token.old_value) is int else 0,
                                         target=target.path, at_ns=self.start,
                                         thread=threading.get_native_id(), **fields))
        except Exception as error:
            capture.error = type(error).__name__[:96]
            capture.stop('metadata-error')

    def close(self, result, outcome):
        capture = self.capture
        try:
            if capture.accepting:
                fields = self.metadata.result(capture, result) if outcome == 'return' else {}
                capture.record('calls', dict(event=outcome, span=self.identity, target=self.target.path,
                                             at_ns=time.monotonic_ns(),
                                             elapsed_ns=time.monotonic_ns() - self.start,
                                             thread_cpu_ns=time.thread_time_ns() - self.cpu, **fields))
                with capture.lock:
                    capture.open_spans -= 1
        except Exception as error:
            capture.error = type(error).__name__[:96]
            capture.stop('metadata-error')
        finally:
            self.parent.reset(self.token)


class LegacyCallMetadata(CallMetadata):
    """Explicit old diagnostic path; NEVER entered by metadata-only captures."""

    def enter(self, capture, arguments):
        return dict(subject=_subject(tuple(arguments.values())))

    def result(self, capture, result):
        return dict(result=_result(result))


def trace_calls(*, expected_pid, output, targets, seconds=60, max_records=20000,
                max_bytes=12 << 20, metadata_only=False):
    """Bounded entry/return/cancel spans; returned callable finishes idempotently.

    metadata_only permits only declaration-owned adapters above. No arbitrary
    arguments, repr, product-key parsing or child/lock/cache instrumentation.
    """
    import asyncio
    import functools
    from contextvars import ContextVar

    if not 0 < len(targets) <= 64 or len(set(targets)) != len(targets):
        raise ValueError('Expected 1..64 distinct targets')
    # Complete validation precedes ALL patching, including descriptor checks.
    resolved = [MethodTarget(path) for path in targets]
    adapters = [CallMetadata.targets[path] if metadata_only else LegacyCallMetadata() for path in targets]
    capture = BoundedCapture(expected_pid=expected_pid, seconds=seconds, output=output,
                             max_records=max_records, max_bytes=max_bytes, metadata_only=metadata_only,
                             streams=('calls', 'events'))
    parent = ContextVar('bounded-call-parent', default=0)

    def instrument(target, metadata):
        original = target.original
        if target.asynchronous:
            @functools.wraps(original)
            async def timed(*args, **kwargs):
                if not capture.accepting:
                    return await original(*args, **kwargs)
                span = CallSpan(capture, target, metadata, parent, args, kwargs)
                result, outcome = None, 'error'
                try:
                    result = await original(*args, **kwargs)
                    outcome = 'return'
                    return result
                except asyncio.CancelledError:
                    outcome = 'cancel'
                    raise
                finally:
                    span.close(result, outcome)
        else:
            @functools.wraps(original)
            def timed(*args, **kwargs):
                if not capture.accepting:
                    return original(*args, **kwargs)
                span = CallSpan(capture, target, metadata, parent, args, kwargs)
                result, outcome = None, 'error'
                try:
                    result = original(*args, **kwargs)
                    outcome = 'return'
                    return result
                finally:
                    span.close(result, outcome)
        return timed

    try:
        for target, metadata in zip(resolved, adapters, strict=True):
            capture.patch(target, instrument(target, metadata))
        return capture.arm()
    except BaseException:
        capture.finish('setup-error')
        raise


def trace_reflows(*, expected_pid, output, seconds=60):
    """Each scoped reflow: duration, roots, widgets placed, shown and hidden."""
    import asyncio
    from textual._compositor import Compositor

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    original, records = Compositor.reflow_subtrees, []

    def timed(self, parent, size, roots, **kwargs):
        roots = tuple(roots)
        begin = time.monotonic_ns()
        result = original(self, parent, size, roots, **kwargs)
        records.append(((time.monotonic_ns() - begin) / 1e6,
                        [f"{type(root).__name__}#{root.id or ''}" for root in roots],
                        None if result is None else (len(result.placed), len(result.shown), len(result.hidden)),
                        len(self._visible_map or ())))
        return result

    def full(name):
        method = getattr(Compositor, name)

        def timed_full(self, parent, size, *args, **kwargs):
            # What the screen was asked to lay out when it could not scope it.
            pending = getattr(parent, "_layout_widgets", {})
            requests = sorted(f"{type(widget).__name__}#{widget.id or ''}"
                              + ("" if widget.styles.auto_dimensions else "!")
                              for widget in pending)
            begin = time.monotonic_ns()
            result = method(self, parent, size, *args, **kwargs)
            records.append(((time.monotonic_ns() - begin) / 1e6, [name, *requests], "full",
                            len(self._visible_map or ())))
            return result

        setattr(Compositor, name, timed_full)
        return name, method

    Compositor.reflow_subtrees = timed
    fulls = [full("reflow"), full("reflow_visible")]

    def finish():
        Compositor.reflow_subtrees = original
        for name, method in fulls:
            setattr(Compositor, name, method)
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(records, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(seconds, finish)


def trace_garbage(*, expected_pid, output, seconds=12, min_objects=1000):
    """What each collection that finds at least ``min_objects`` unreachable objects collected.

    For ``seconds`` the collector keeps what it finds (DEBUG_SAVEALL); after
    each collection the found objects are counted by type and released.
    """
    import asyncio
    import collections
    import gc

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    records = []
    state = {}

    def collected(phase, info):
        if phase == "start":
            state["begin"] = time.monotonic_ns()
            return
        found = gc.garbage[:]
        gc.garbage.clear()
        if len(found) >= min_objects:
            types = collections.Counter(f"{type(item).__module__}.{type(item).__qualname__}" for item in found)
            # Exceptions and frames held in cycles: which raised, and where.
            types.update(f"raised {type(item).__qualname__}: {str(item)[:60]}"
                         for item in found if isinstance(item, BaseException))
            types.update(f"frame {item.f_code.co_qualname} {item.f_code.co_filename.rsplit('/', 2)[-1]}"
                         for item in found if type(item).__name__ == "frame")
            # The objects nothing else refers to first: what owned the cycle.
            causes = [(name, count) for name, count in types.most_common() if name.startswith(("raised", "frame"))]
            records.append((state["begin"], (time.monotonic_ns() - state["begin"]) / 1e6, info["generation"],
                            len(found), types.most_common(60) + causes[:40]))
        del found

    gc.set_debug(gc.DEBUG_SAVEALL)
    gc.callbacks.append(collected)

    def finish():
        gc.callbacks.remove(collected)
        gc.set_debug(0)
        gc.garbage.clear()
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(records, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(seconds, finish)


def heap_census(*, expected_pid, output, after=10):
    """``after`` seconds from now: the collector's tracked, unfrozen objects counted by type.

    These are what each pass of the cyclic collector scans (frozen objects are not).
    """
    import asyncio
    import collections
    import gc

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")

    def count():
        with measuring_pause():
            objects = gc.get_objects()
            types = collections.Counter(f"{type(item).__module__}.{type(item).__qualname__}" for item in objects)
            # Bound built-ins and weak references: which owners hold them.
            types.update(f"bound {type(item.__self__).__qualname__}.{item.__name__}" for item in objects
                         if type(item).__name__ == "builtin_function_or_method" and item.__self__ is not None)
            types.update(f"weakref to {type(target).__qualname__}" for item in objects
                         if type(item).__name__ == "ReferenceType" and (target := item()) is not None)
            total = len(objects)
            del objects
            # Each ABC's isinstance/issubclass caches (weak references to classes).
            import _abc
            from abc import ABCMeta
            seen, pending, caches = set(), [object], collections.Counter()
            while pending:
                cls = pending.pop()
                for sub in type.__subclasses__(cls) if isinstance(cls, type) else ():
                    if sub not in seen:
                        seen.add(sub)
                        pending.append(sub)
                        if isinstance(sub, ABCMeta):
                            registry, cache, negative, _version = _abc._get_dump(sub)
                            if len(cache) + len(negative) >= 1:
                                caches[f"abc cache {sub.__module__}.{sub.__qualname__}"] = len(cache) + len(negative)
            types.update(caches)
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump({"tracked": total, "frozen": gc.get_freeze_count(), "types": types.most_common(3000)}, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(after, count)


def collect_all(*, expected_pid, output, after=70):
    """``after`` seconds from now: one full collection, split into its scan and its frees.

    The first pass keeps what it finds (DEBUG_SAVEALL), so its time is the
    scan of the whole unfrozen heap and the found objects can be counted by
    type; the second pass scans again and frees them. The difference is what
    freeing that garbage costs. Both run inside a measuring pause.
    """
    import asyncio
    import collections
    import gc

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")

    def collect():
        with measuring_pause():
            tracked = len(gc.get_objects())
            gc.set_debug(gc.DEBUG_SAVEALL)
            begin = time.monotonic_ns()
            gc.collect()
            scanned = time.monotonic_ns()
            gc.set_debug(0)
            found = gc.garbage[:]
            gc.garbage.clear()
            types = collections.Counter(f"{type(item).__module__}.{type(item).__qualname__}" for item in found)
            sizes, item = collections.Counter(), None
            for item in found:
                if isinstance(item, (list, tuple, dict, set)):
                    sizes[f"{type(item).__name__} items"] += len(item)
            count = len(found)
            del found, item
            begin_free = time.monotonic_ns()
            gc.collect()
            freed = time.monotonic_ns()
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump({"tracked_before": tracked, "found": count, "scan_ms": (scanned - begin) / 1e6,
                       "scan_and_free_ms": (freed - begin_free) / 1e6, "tracked_after": len(gc.get_objects()),
                       "types": types.most_common(60), "container_items": sizes.most_common()}, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(after, collect)


def heap_components(*, expected_pid, output, after=100):
    """``after`` seconds from now: how the unfrozen heap hangs together.

    A collector increment takes an object and everything unfrozen it can
    reach, so its pause is the size of that reachable set, not of the
    increment's budget. This records the largest strongly connected group,
    what it reaches, by type, and how much it would reach if objects of one
    type were not followed (which type ties the set together).
    """
    import asyncio
    import collections
    import gc

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")

    def name(item):
        return f"{type(item).__module__}.{type(item).__qualname__}"

    def measure():
        with measuring_pause():
            objects = gc.get_objects()
            index = {id(item): position for position, item in enumerate(objects)}
            count = len(objects)
            types = [name(item) for item in objects]
            edges = [[index[id(target)] for target in gc.get_referents(item) if id(target) in index]
                     for item in objects]

            def reach(seeds, skip=None):
                seen = bytearray(count)
                pending = list(seeds)
                for seed in pending:
                    seen[seed] = 1
                total = 0
                while pending:
                    node = pending.pop()
                    total += 1
                    if skip is not None and types[node] == skip:
                        continue
                    for target in edges[node]:
                        if not seen[target]:
                            seen[target] = 1
                            pending.append(target)
                return total, seen

            # Strongly connected groups (iterative Tarjan).
            order, low, on_stack, stack, groups = [-1] * count, [0] * count, bytearray(count), [], []
            counter = 0
            for start in range(count):
                if order[start] != -1:
                    continue
                work = [(start, 0)]
                while work:
                    node, edge = work.pop()
                    if edge == 0:
                        order[node] = low[node] = counter
                        counter += 1
                        stack.append(node)
                        on_stack[node] = 1
                    targets = edges[node]
                    descended = False
                    while edge < len(targets):
                        target = targets[edge]
                        edge += 1
                        if order[target] == -1:
                            work.append((node, edge))
                            work.append((target, 0))
                            descended = True
                            break
                        if on_stack[target] and order[target] < low[node]:
                            low[node] = order[target]
                    if descended:
                        continue
                    if low[node] == order[node]:
                        group = []
                        while True:
                            member = stack.pop()
                            on_stack[member] = 0
                            group.append(member)
                            if member == node:
                                break
                        if len(group) > 50:
                            groups.append(group)
                    if work:
                        parent = work[-1][0]
                        if low[node] < low[parent]:
                            low[parent] = low[node]
            groups.sort(key=len, reverse=True)
            report = {"tracked": count, "edges": sum(map(len, edges)), "groups": []}
            for group in groups[:4]:
                total, seen = reach(group[:1])
                reached = collections.Counter(types[node] for node in range(count) if seen[node])
                inside = collections.Counter(types[node] for node in group)
                cuts = sorted(((reach(group[:1], skip=kind)[0], kind) for kind, _ in reached.most_common(40)
                               if types[group[0]] != kind))[:15]
                report["groups"].append({"size": len(group), "types": inside.most_common(25), "reaches": total,
                                         "reached_types": reached.most_common(40), "reaches_without_type": cuts})
            # Objects no unfrozen object refers to: where increments that stay small begin.
            referred = bytearray(count)
            for targets in edges:
                for target in targets:
                    referred[target] = 1
            report["unreferred_types"] = collections.Counter(
                types[node] for node in range(count) if not referred[node]).most_common(25)
            del objects, index, edges
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(report, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(after, measure)


def freeze_heap(*, expected_pid, output):
    """Experiment: freeze the collector's current heap now (what a later freeze policy would do)."""
    import gc

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    with measuring_pause():
        before = len(gc.get_objects())
        gc.freeze()
    with open(output, "w") as file:
        json.dump({"frozen_now": before, "frozen_total": gc.get_freeze_count()}, file)


def trace_abc_growth(*, expected_pid, output, seconds=40):
    """Who adds entries to ABC isinstance/issubclass caches (each is two collector-tracked objects)."""
    import _abc
    import asyncio
    import collections
    from abc import ABCMeta

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    sources = collections.Counter()
    instancecheck, subclasscheck = ABCMeta.__instancecheck__, ABCMeta.__subclasscheck__

    def size(cls):
        _registry, cache, negative, _version = _abc._get_dump(cls)
        return len(cache) + len(negative)

    def record(cls, checked):
        caller, chain = sys._getframe(2), []
        while caller is not None and len(chain) < 5:
            chain.append(f"{caller.f_code.co_qualname} {caller.f_code.co_filename.rsplit('/', 2)[-1]}")
            caller = caller.f_back
        sources[" < ".join(chain)] += 1

    def counted_instancecheck(cls, instance):
        before = size(cls)
        result = instancecheck(cls, instance)
        if size(cls) > before:
            record(cls, type(instance))
        return result

    def counted_subclasscheck(cls, subclass):
        before = size(cls)
        result = subclasscheck(cls, subclass)
        if size(cls) > before:
            record(cls, subclass)
        return result

    ABCMeta.__instancecheck__, ABCMeta.__subclasscheck__ = counted_instancecheck, counted_subclasscheck

    def finish():
        ABCMeta.__instancecheck__, ABCMeta.__subclasscheck__ = instancecheck, subclasscheck
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(sources.most_common(40), file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(seconds, finish)


def trace_posts(*, expected_pid, output, seconds=40):
    """Every message posted to a screen: when, its type and who posted it."""
    import asyncio
    from textual.message_pump import MessagePump
    from textual.screen import Screen

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    post, records = MessagePump.post_message, []

    def recorded(self, message):
        if isinstance(self, Screen):
            caller, chain = sys._getframe(1), []
            while caller is not None and len(chain) < 6:
                chain.append(f"{caller.f_code.co_qualname}:{caller.f_lineno}")
                caller = caller.f_back
            sender = getattr(message, "widget", None) or getattr(message, "_sender", None)
            records.append((time.monotonic_ns(), type(message).__qualname__, type(sender).__name__, " < ".join(chain)))
        return post(self, message)

    MessagePump.post_message = recorded

    def finish():
        MessagePump.post_message = post
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(records, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(seconds, finish)


def trace_rules(*, expected_pid, output, seconds=60):
    """Each committed style-rule change: when, on which node, which rules, and whether geometry."""
    import asyncio
    from textual.css.styles import Styles

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    original, records = Styles._update_rules, []

    def recorded(self, rules, removals=()):
        rules, removals = tuple(rules), tuple(removals)
        before = dict(self._rules)
        begin = time.monotonic_ns()
        changed = original(self, rules, removals)
        if changed and (node := self.node) is not None:
            keys = sorted({key for key, value in rules if before.get(key) != value}
                          | {key for key in removals if key in before})
            records.append((begin, (time.monotonic_ns() - begin) / 1e6,
                            f"{type(node).__name__}#{getattr(node, 'id', None) or ''}", keys))
        return changed

    Styles._update_rules = recorded

    def finish():
        Styles._update_rules = original
        partial = output + ".partial"
        with open(partial, "w") as file:
            json.dump(records, file)
        os.rename(partial, output)

    asyncio.get_running_loop().call_later(seconds, finish)


def trace_exit(*, expected_pid, output):
    """Write who asks the app to exit, and when the process ends, as it happens."""
    import atexit
    import traceback
    from textual.app import App

    if os.getpid() != expected_pid:
        raise RuntimeError("Unexpected capture process")
    original = App.exit

    def note(text):
        with open(output, "a") as file:
            file.write(f"{time.time():.3f} {text}\n")

    def exit(self, *args, **kwargs):
        note("App.exit " + repr((args, kwargs)) + "\n" + "".join(traceback.format_stack(limit=25)))
        return original(self, *args, **kwargs)

    App.exit = exit
    atexit.register(note, "process exit")
    note("installed")


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))] if ordered else float("nan")


def summarize(path):
    data = json.load(open(path))
    # Leave out what the scenario's own snapshots caused: a frame whose
    # interval, or a lag whose wait, overlaps a snapshot (5 ms either side).
    pauses = [(begin - 5_000_000, end + 5_000_000) for begin, end in data.get("pauses", [])]

    def measured(begin, end):
        return not any(begin < pause_end and pause_begin < end for pause_begin, pause_end in pauses)

    frames = [frame for previous, frame in zip([None, *data["frames"]], data["frames"])
              if measured(previous[0] if previous else frame[0], frame[0])]
    data["lags"] = [(at, lag) for at, lag in data.get("lags", []) if measured(at - lag * 1e6, at)]
    data["inputs"] = [entry for entry in data["inputs"] if measured(entry[0], entry[1] or entry[0])]
    work = [frame[1] for frame in frames]
    # The longest stretch per frame the loop could not paint in (older
    # captures lack it: their frame work is the only measure).
    stalls = [frame[2] if len(frame) > 2 else frame[1] for frame in frames]
    ends = [frame[0] for frame in frames]
    latencies = []
    for arrived, handled, *_ in data["inputs"]:
        if handled is not None and (position := bisect.bisect_left(ends, handled)) < len(ends):
            latencies.append((ends[position] - arrived) / 1e6)
    return {
        "snapshot_pauses": len(pauses), "frames_left_out": len(data["frames"]) - len(frames),
        "frames": len(work), "inputs": len(data["inputs"]), "painted_inputs": len(latencies),
        "frame_median_ms": round(statistics.median(work), 1) if work else None,
        "frame_p95_ms": round(percentile(work, .95), 1),
        "frame_p99_ms": round(percentile(work, .99), 1),
        "input_to_paint_median_ms": round(statistics.median(latencies), 1) if latencies else None,
        "input_to_paint_p95_ms": round(percentile(latencies, .95), 1),
        "input_to_paint_p99_ms": round(percentile(latencies, .99), 1),
        "frame_worst_ms": round(max(work), 1) if work else None,
        "frames_over_16_33_50": [sum(value > limit for value in work) for limit in (16, 33, 50)],
        "stall_p95_ms": round(percentile(stalls, .95), 1),
        "stall_worst_ms": round(max(stalls), 1) if stalls else None,
        "stalls_over_16_33_50": [sum(value > limit for value in stalls) for limit in (16, 33, 50)],
        **lag_summary(data.get("lags", [])),
        # Tab switches' loop turns over 20 us: how many and the longest.
        "switch_turns": [len(data.get("switch_steps", [])),
                         round(max((spent for _begin, spent in data.get("switch_steps", [])), default=0), 2)],
        # Per layout run in steps (or with a step over 4 ms): steps and the longest step.
        "stepped_layouts": [[len(steps), round(max(steps), 2)]
                            for _begin, _step_ns, steps in data.get("stepped_layouts", []) if steps],
    }


def lag_summary(lags):
    """How long input or paint would have waited: the loop's lateness."""
    if not lags:
        return {}
    late = [lag for _at, lag in lags]
    return {"lag_p95_ms": round(percentile(late, .95), 1), "lag_p99_ms": round(percentile(late, .99), 1),
            "lag_worst_ms": round(max(late), 1),
            "lags_over_16_33_50": [sum(value > limit for value in late) for limit in (16, 33, 50)]}


if __name__ == "__main__":
    print(json.dumps(summarize(sys.argv[1]), indent=2))
