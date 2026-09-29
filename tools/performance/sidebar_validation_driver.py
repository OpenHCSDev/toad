"""Opt-in observer for real-terminal input, frame work, flush and loop stalls."""

from collections import Counter, deque
import gc
from hashlib import sha256
from functools import update_wrapper
import importlib.util
import json
import logging
import os
from pathlib import Path
import signal
import sys
import threading
import time
import traceback

from textual import events
from textual.drivers.linux_driver import LinuxDriver

records = deque(maxlen=100000)
dispatch_counts = {}
key_dispatches = {}


def record(event, **values):
    records.append({"event": event, "ns": time.monotonic_ns(), **values})


def install_observer():
    if os.environ.get("TOAD_VALIDATION_ARRANGEMENTS") == "1":
        from textual.widget import Widget

        widget_arrange = Widget.arrange

        def measured_arrangement(self, size, optimal=False):
            hits = self._arrangement_cache.hits
            revision = self._nodes._updates, self._layout_updates, self.styles._cache_key
            begin = time.monotonic_ns()
            result = widget_arrange(self, size, optimal=optimal)
            duration_ms = (time.monotonic_ns() - begin) / 1e6
            record("arrangement", begin_ns=begin, duration_ms=duration_ms,
                   owner=id(self), widget=type(self).__name__, container=list(size),
                   revision=revision, optimal=optimal,
                   hit=self._arrangement_cache.hits > hits,
                   result=[list(result.scroll_spacing), [
                       [list(p.region), list(p.offset), list(p.margin), id(p.widget),
                        p.order, p.fixed, p.overlay, p.absolute] for p in result.placements]])
            return result

        Widget.arrange = measured_arrangement
    if os.environ.get("TOAD_VALIDATION_BOX_MODELS") == "1":
        from textual.widget import Widget

        get_box = Widget._get_box_model

        def measured_box(self, container, viewport, width_fraction, height_fraction,
                         constrain_width=False, greedy=True):
            hits = self._box_model_cache.hits
            begin = time.monotonic_ns()
            result = get_box(self, container, viewport, width_fraction, height_fraction,
                             constrain_width=constrain_width, greedy=greedy)
            record("box_model", begin_ns=begin, duration_ms=(time.monotonic_ns()-begin)/1e6,
                   owner=id(self), widget=type(self).__name__, container=list(container),
                   viewport=list(viewport), width_fraction=str(width_fraction), height_fraction=str(height_fraction),
                   revision=self._box_model_revision, hit=self._box_model_cache.hits > hits,
                   result=[str(result.width), str(result.height)], greedy=greedy)
            return result

        Widget._get_box_model = measured_box
    if os.environ.get("TOAD_VALIDATION_FILTER_PROBE"):
        from textual.message_pump import MessagePump
        from toad.widgets.prompt import PromptTextArea
        dispatch = MessagePump._dispatch_message
        route_probe = bool(os.environ.get("TOAD_VALIDATION_KEY_ROUTE"))

        if route_probe:
            post = MessagePump.post_message

            def observed_post(self, message):
                if isinstance(message, events.Key) and message.key == "x":
                    record("key_route", phase="queued", owner=type(self).__name__,
                           input_ns=key_dispatches.get(id(message)))
                return post(self, message)

            MessagePump.post_message = observed_post

        async def observed_dispatch(self, message):
            sent = None
            if route_probe and isinstance(message, events.Key) and message.key == "x":
                sent = key_dispatches.get(id(message))
                record("key_route", phase="dispatch_begin", owner=type(self).__name__, input_ns=sent)
            try:
                return await dispatch(self, message)
            finally:
                if route_probe and sent is not None:
                    record("key_route", phase="dispatch_end", owner=type(self).__name__, input_ns=sent)
                if isinstance(self, PromptTextArea) and isinstance(message, events.Key) and message.key == "x":
                    sent = key_dispatches.pop(id(message), None)
                    record("prompt_key_applied", key=message.key, mode=self.app.current_mode,
                           text_length=len(self.text), input_ns=sent,
                           acknowledgment_ms=(time.monotonic_ns()-sent)/1e6 if sent is not None else None)

        MessagePump._dispatch_message = observed_dispatch
    if os.environ.get("TOAD_VALIDATION_LEGACY_MARKDOWN_MEASUREMENT") == "1":
        from textual.widget import Widget
        from toad.widgets.prepared_markdown import PreparedConversationMarkdown
        PreparedConversationMarkdown._measured_virtual_size_requires_layout = Widget._measured_virtual_size_requires_layout
    if os.environ.get("TOAD_VALIDATION_LAYOUT_CAUSES"):
        from textual.widget import Widget
        refresh = Widget.refresh

        def requested(self, *args, **kwargs):
            if kwargs.get("layout") and not self._layout_required:
                caller = sys._getframe(1)
                callers = []
                for _ in range(10):
                    if caller is None:
                        break
                    callers.append((Path(caller.f_code.co_filename).name, caller.f_code.co_name, caller.f_lineno))
                    caller = caller.f_back
                del caller
                record("layout_request", widget=type(self).__name__, widget_id=self.id, identity=id(self), callers=callers)
            return refresh(self, *args, **kwargs)

        Widget.refresh = requested
    from toad.widgets.side_bar import SideBar
    toggle = SideBar.toggle

    def measured_toggle(self, *args, **kwargs):
        begin = time.monotonic_ns()
        cpu = time.thread_time_ns()
        try:
            return toggle(self, *args, **kwargs)
        finally:
            record("sidebar_toggle", begin_ns=begin, duration_ms=(time.monotonic_ns()-begin)/1e6,
                   cpu_ms=(time.thread_time_ns()-cpu)/1e6, sidebar=self.id, collapsed=self.collapsed)

    SideBar.toggle = measured_toggle
    from toad.screens.session_view import SessionView
    if os.environ.get("TOAD_VALIDATION_COLD_PRESENTATIONS") == "1":
        SessionView.RETAIN_INACTIVE_PRESENTATION = False
    if os.environ.get("TOAD_VALIDATION_COLD_PAINT") == "1":
        SessionView.RETAIN_INACTIVE_PAINT = False
    from toad.app import ToadApp
    from toad.widgets.conversation import Conversation
    exception_handler = ToadApp._handle_exception

    def observed_exception(self, error):
        path = os.environ.get("TOAD_VALIDATION_TRACE")
        if path:
            with Path(path + ".exceptions.txt").open("a") as output:
                output.write("".join(traceback.format_exception(error)))
                if isinstance(getattr(error, "error", None), BaseException):
                    output.write("".join(traceback.format_exception(error.error)))
        record("app_exception", error_type=type(error).__name__, error=str(error))
        return exception_handler(self, error)

    ToadApp._handle_exception = observed_exception

    if os.environ.get("TOAD_VALIDATION_UNGATED_STARTUP") == "1":
        # Diagnostic policy control: ordinary after-refresh scheduling instead
        # of the first actual presentation boundary. Not a production setting.
        SessionView._first_frame_presented = True

    navigation_methods = [(ToadApp, "_switch_mode_ready"), (SessionView, "prepare_navigation"),
                          (SessionView, "layout_navigation"), (Conversation, "on_transcript_snapshot"),
                          (Conversation, "on_agent_ready")]
    if os.environ.get("TOAD_VALIDATION_OPEN_STAGES"):
        from textual.widget import Widget
        from toad.sidebar_observation import SidebarObservation
        from toad.sidebar_projection import SidebarProjection
        from toad.widgets.session_tabs import SessionsTabs
        from toad.navigation_preparation import NavigationReader
        navigation_methods.extend(((ToadApp, "new_session_screen"), (Conversation, "initialize_view"),
                                   (SidebarObservation, "present_cached"), (SidebarProjection, "rebuild"),
                                   (SessionsTabs, "_sync_tabs"), (NavigationReader, "read")))
        constructor = Widget.__init__
        preprocess = Widget._pre_process

        def measured_constructor(self, *args, **kwargs):
            begin, cpu = time.monotonic_ns(), time.thread_time_ns()
            try:
                return constructor(self, *args, **kwargs)
            finally:
                record("widget_construct", widget=type(self).__name__, begin_ns=begin,
                       duration_ms=(time.monotonic_ns()-begin)/1e6, cpu_ms=(time.thread_time_ns()-cpu)/1e6)

        async def measured_preprocess(self):
            begin = time.monotonic_ns()
            try:
                return await preprocess(self)
            finally:
                record("widget_mount", widget=type(self).__name__, begin_ns=begin,
                       duration_ms=(time.monotonic_ns()-begin)/1e6)

        Widget.__init__ = measured_constructor
        Widget._pre_process = measured_preprocess

    for owner, method in navigation_methods:
        original_method = getattr(owner, method)

        async def measured_navigation(self, *args, _function=original_method, _name=method, **kwargs):
            begin = time.monotonic_ns()
            try:
                return await _function(self, *args, **kwargs)
            finally:
                record("navigation_stage", stage=_name, begin_ns=begin,
                       duration_ms=(time.monotonic_ns()-begin)/1e6,
                       mode=args[0] if _name == "_switch_mode_ready" and args else
                       self.app.current_mode if hasattr(self, "app") else None,
                       owner=type(self).__name__)

        # Textual stores @on handlers by function identity in the class registry.
        # Keep metadata and that registry aligned: replacing only the attribute
        # would invoke the old decorated function AND the new name-based wrapper.
        update_wrapper(measured_navigation, original_method)
        for handlers in owner.__dict__.get("_decorated_handlers", {}).values():
            handlers[:] = [(measured_navigation if handler is original_method else handler, selectors)
                           for handler, selectors in handlers]
        setattr(owner, method, measured_navigation)
    from toad.acp.messages import TranscriptSnapshot
    from toad.agent import AgentReady
    dispatch_probe = object.__new__(Conversation)
    for message in (TranscriptSnapshot((), None), AgentReady()):
        count = len(list(dispatch_probe._get_dispatch_methods(message.handler_name, message)))
        dispatch_counts[type(message).__name__] = count
        assert count == 1, (type(message).__name__, count)
    for name in ("_refresh_layout", "_compositor_refresh"):
        original = getattr(SessionView, name)

        def measured(self, *args, _function=original, _name=name, **kwargs):
            begin = time.monotonic_ns()
            cpu = time.thread_time_ns()
            try:
                return _function(self, *args, **kwargs)
            finally:
                record(_name, begin_ns=begin, duration_ms=(time.monotonic_ns()-begin)/1e6,
                       cpu_ms=(time.thread_time_ns()-cpu)/1e6, mode=self.id,
                       batched=self.app._batch_count > 0,
                       viewport=self._use_viewport_layout(), anchors=len(self.viewport_presentation.anchors),
                       visible_map=len(self._compositor._visible_map or {}),
                       full_map=len(self._compositor._full_map),
                       callbacks=len(self._callbacks))

        setattr(SessionView, name, measured)

    from textual._compositor import Compositor
    arrange = Compositor._arrange_root

    def measured_arrange(self, *args, **kwargs):
        begin = time.monotonic_ns()
        caller = sys._getframe(1)
        callers = []
        for _ in range(9):
            if caller is None:
                break
            callers.append((caller.f_code.co_filename.rsplit("/", 1)[-1], caller.f_code.co_name, caller.f_lineno))
            caller = caller.f_back
        del caller
        try:
            return arrange(self, *args, **kwargs)
        finally:
            duration = (time.monotonic_ns()-begin)/1e6
            if duration >= 3:
                record("arrange_root", begin_ns=begin, duration_ms=duration,
                       visible_only=kwargs.get("visible_only"), callers=callers)

    Compositor._arrange_root = measured_arrange

    if importlib.util.find_spec("toad.work_preparation") is not None:
        from toad.work_preparation import PreparationRuntime
        execute = PreparationRuntime._execute
        submit = PreparationRuntime.submit

        async def measured_execution(self, key, work):
            begin = time.monotonic_ns()
            try:
                return await execute(self, key, work)
            finally:
                record("prepared_work_execute", begin_ns=begin, duration_ms=(time.monotonic_ns()-begin)/1e6,
                       kind=type(work).__name__)

        async def measured_submission(self, work):
            begin = time.monotonic_ns()
            try:
                return await submit(self, work)
            finally:
                record("prepared_work_submit", begin_ns=begin, duration_ms=(time.monotonic_ns()-begin)/1e6,
                       kind=type(work).__name__)

        PreparationRuntime._execute = measured_execution
        PreparationRuntime.submit = measured_submission

    from toad.acp.agent import Agent
    read = Agent.get_transcript_page

    async def measured_read(self, *args, **kwargs):
        begin = time.monotonic_ns()
        try:
            return await read(self, *args, **kwargs)
        finally:
            record("transcript_read", begin_ns=begin, duration_ms=(time.monotonic_ns()-begin)/1e6)

    Agent.get_transcript_page = measured_read
    if importlib.util.find_spec("toad.transcript_preparation") is not None:
        from toad.transcript_preparation import TranscriptPageBuffer, TranscriptPageWork
        get = TranscriptPageBuffer.get

        async def measured_get(self, request):
            from textual.worker import active_worker

            begin = time.monotonic_ns()
            key = TranscriptPageWork(self.scope, self.loader, self.through, request).work_key
            cached = key in self.runtime._ready
            shared = key in self.runtime._pending
            worker = active_worker.get(None)
            try:
                return await get(self, request)
            finally:
                record("prepared_history_get", begin_ns=begin,
                       duration_ms=(time.monotonic_ns()-begin)/1e6,
                       cached=cached, shared=shared, ready=len(self.runtime._ready), retained_bytes=self.runtime.retained_bytes,
                       group=worker.group if worker is not None else None)

        TranscriptPageBuffer.get = measured_get


class ValidationDriver(LinuxDriver):
    def __init__(self, *args, **kwargs):
        self._ui_thread = threading.get_ident()
        self._frame = 0
        self._running_observer = True
        self._previous_tick = time.monotonic_ns()
        self._gc_started = None
        super().__init__(*args, **kwargs)
        self._asyncio_log_handler = None
        self._diagnostic_tree_logged = False
        self._focused_profiler = None
        self._focused_profile_index = 0
        self._focused_profile_kind = os.environ.get("TOAD_VALIDATION_FOCUSED_PROFILE")
        if self._focused_profile_kind:
            self._focused_profile_base = os.environ["TOAD_VALIDATION_PROFILE_BASE"]
            signal.signal(signal.SIGRTMIN, lambda *_: self._app.call_later(self._toggle_focused_profile))
            self._profile_receipt("idle")
        if asyncio_log := os.environ.get("TOAD_VALIDATION_ASYNCIO_LOG"):
            self._asyncio_log_handler = logging.FileHandler(asyncio_log, mode="w")
            self._asyncio_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logging.getLogger("asyncio").addHandler(self._asyncio_log_handler)
            self._loop.set_debug(True)
            self._loop.slow_callback_duration = .05
        self._loop.call_soon(self._tick)
        gc.callbacks.append(self._gc)
        signal.signal(signal.SIGUSR1, lambda *_: self._app.call_after_refresh(self._snapshot))
        signal.signal(signal.SIGRTMAX, lambda *_: self._stalled_snapshot())
        if os.environ.get("TOAD_VALIDATION_CENSUS"):
            signal.signal(signal.SIGUSR2, lambda *_: self._app.call_later(self._census))

    def _profile_receipt(self, status):
        Path(self._focused_profile_base + "-profile-state.json").write_text(json.dumps({
            "pid": os.getpid(), "status": status, "ns": time.monotonic_ns(),
            "kind": self._focused_profile_kind,
            "index": self._focused_profile_index,
        }))

    def _toggle_focused_profile(self):
        if self._focused_profiler is None:
            self._focused_profile_index += 1
            self._focused_profile_path = f"{self._focused_profile_base}-{self._focused_profile_index:02}"
            if self._focused_profile_kind == "memray":
                import memray
                self._focused_profiler = memray.Tracker(
                    self._focused_profile_path + ".memray", trace_python_allocators=True,
                    native_traces=True, file_format=memray.FileFormat.AGGREGATED_ALLOCATIONS,
                )
                self._focused_profiler.__enter__()
            else:
                import cProfile
                self._focused_profiler = cProfile.Profile()
                self._focused_profiler.enable()
            self._profile_receipt("running")
        else:
            if self._focused_profile_kind == "memray":
                self._focused_profiler.__exit__(None, None, None)
            else:
                self._focused_profiler.disable()
                self._focused_profiler.dump_stats(self._focused_profile_path + ".pstats")
            self._focused_profiler = None
            self._profile_receipt("complete")

    def _tick(self):
        now = time.monotonic_ns()
        gap = (now - self._previous_tick) / 1e6
        if gap >= 5:
            record("loop_gap", begin_ns=self._previous_tick, duration_ms=gap)
        self._previous_tick = now
        if self._running_observer:
            self._loop.call_later(.002, self._tick)

    def _gc(self, phase, info):
        if phase == "start":
            self._gc_started = (time.monotonic_ns(), time.thread_time_ns(), threading.get_ident(), gc.get_count())
        elif self._gc_started is not None:
            begin, cpu, thread, counts = self._gc_started
            duration = (time.monotonic_ns()-begin)/1e6
            callers = []
            if duration >= 10:
                frame = sys._getframe(1)
                for _ in range(8):
                    if frame is None:
                        break
                    callers.append((frame.f_code.co_filename.rsplit("/", 1)[-1], frame.f_code.co_name, frame.f_lineno))
                    frame = frame.f_back
                del frame
            record("gc", begin_ns=begin, duration_ms=duration,
                   cpu_ms=(time.thread_time_ns()-cpu)/1e6, ui_thread=thread == self._ui_thread,
                   counts_before=counts, enabled=gc.isenabled(),
                   realtime_animations=self._app._realtime_animation_count,
                   generation=info["generation"], collected=info["collected"], callers=callers)
            self._gc_started = None

    def send_message(self, message):
        if os.environ.get("TOAD_VALIDATION_FILTER_PROBE") and isinstance(message, events.Key):
            if message.key == "x":
                key_dispatches[id(message)] = time.monotonic_ns()
            record("input_key", key=message.key)
        if isinstance(message, (events.MouseDown, events.MouseUp, events.MouseMove, events.MouseScrollDown, events.MouseScrollUp)):
            record("input", message=type(message).__name__, x=message.x, y=message.y)
        return super().send_message(message)

    def _census(self):
        # Explicit diagnostics outside timed actions. Do not collect, freeze or
        # disable GC; release the temporary strong references immediately.
        begin = time.monotonic_ns()
        objects = gc.get_objects()
        from widget_census import widget_cohorts

        cohorts = widget_cohorts(objects, self._app,
                                 limit=int(os.environ.get("TOAD_VALIDATION_CENSUS_LIMIT", "60")))
        counts = Counter((type(value).__module__, type(value).__qualname__) for value in objects)
        from textual._styles_cache import StylesCache
        from textual.widget import Widget
        from textual.dom import DOMNode
        widget_counts = Counter((type(value).__name__, value.is_mounted, value._closing, value._closed)
                                for value in objects if isinstance(value, Widget))
        measurement_entries = Counter()
        reactive_subscriptions = Counter()
        closed_watch_paths = Counter()
        for value in objects:
            if issubclass(type(value), DOMNode):
                for attribute, watchers in value.__dict__.get("__watchers", {}).items():
                    for subscriber, _callback in watchers:
                        reactive_subscriptions["closed" if subscriber._closed else "live"] += 1
                        if subscriber._closed:
                            closed_watch_paths[(type(value).__name__, attribute, type(subscriber).__name__)] += 1
            if isinstance(value, Widget):
                revision = value._box_model_revision
                for key in value._box_model_cache.keys():
                    # The owner-published suffix includes structure and optional proof
                    # epochs; comparing a historical two-field suffix mislabels it.
                    measurement_entries[
                        "owner_generation" if revision is not None and key[-len(revision):] == revision
                        else "other_generation"
                    ] += 1
        total = len(objects)
        del objects
        data = {"ns": time.monotonic_ns(), "pid": os.getpid(), "tracked": total,
                "widget_cohorts": cohorts,
                "counts": counts.most_common(60), "widgets": widget_counts.most_common(50),
                "closed_widgets": {name: count for (name, _mounted, _closing, closed), count in widget_counts.items() if closed},
                 "measurement_entries": dict(measurement_entries),
                 "paint_color_cache": StylesCache.get_inner_outer.cache_info()._asdict(),
                 "reactive_subscriptions": dict(reactive_subscriptions),
                 "closed_reactive_watch_paths": closed_watch_paths.most_common(20),
                "gc": gc.get_stats(),
                "allocated_blocks": sys.getallocatedblocks(), "tabs": len(self._app.open_tabs),
                "duration_ms": (time.monotonic_ns()-begin)/1e6}
        with Path(os.environ["TOAD_VALIDATION_CENSUS"]).open("a") as stream:
            stream.write(json.dumps(data) + "\n")

    def _stalled_snapshot(self):
        """Read-only failure evidence independent of the refresh callback queue."""
        from toad.widgets.history_anchor import HistoryWindow

        app = self._app
        screens = []
        for mode, stack in app._screen_stacks.items():
            for screen in stack:
                timer = screen._update_timer
                task = timer._task
                screens.append({"mode": mode, "current": screen.is_current,
                    "callbacks": len(screen._callbacks), "layout_required": screen._layout_required,
                    "repaint_required": screen._repaint_required, "scroll_required": screen._scroll_required,
                    "layout_nodes": len(screen._layout_widgets), "dirty_nodes": len(screen._dirty_widgets),
                    "timer_task_done": None if task is None else task.done(),
                    "timer_error": (repr(task.exception()) if task is not None and task.done()
                                    and not task.cancelled() else None),
                    "history": [{"locked": window.history_lock.locked(),
                                 "anchor": repr(window.history_anchor.widget) if window.history_anchor else None,
                                 "anchor_attached": window.history_anchor.widget.is_attached if window.history_anchor else None,
                                 "layout_ready": window.history_layout_ready.is_set() if window.history_layout_ready else None,
                                 "managed_anchor": window in screen.viewport_presentation.anchors}
                                for window in screen.query(HistoryWindow)]})
        Path(os.environ["TOAD_VALIDATION_TRACE"] + ".stalled.json").write_text(json.dumps({
            "batch_count": app._batch_count, "current_mode": app.current_mode,
            "atomic_mode_switch": app._atomic_mode_switch, "pending_mode_switch": app._pending_mode_switch,
            "screens": screens}, indent=2))
        Path(os.environ["TOAD_VALIDATION_TRACE"]).write_text(json.dumps(list(records)))

    def flush(self):
        result = super().flush()
        if threading.get_ident() == self._ui_thread and self._writer_thread:
            self._frame += 1
            frame = self._frame
            mode = self._app.current_mode
            record("frame_enqueued", frame=frame, mode=mode)
            self.call_after_flush(lambda: record("frame_flushed", frame=frame, mode=mode))
        return result

    def _snapshot(self):
        from agent_comms.transcript_events import TranscriptCodec
        from toad.widgets.comms_sidebar import CommsRow, ThreadRow
        from toad.widgets.comms_sidebar import CommsSidebar
        from toad.widgets.comms_chat import CommsChatView
        from toad.widgets.conversation import Conversation, ThreadLoading
        from toad.widgets.history_anchor import HistoryWindow
        from toad.widgets.side_bar import SideBar, SideBarToggle, SidebarResizeHandle
        from toad.widgets.session_tabs import SessionLabel, SessionsTabs
        from toad.widgets.transcript_history import TranscriptHistory, HistoryEdge, TranscriptFragmentView
        from toad.widgets.prompt import PromptTextArea
        from textual.widgets._markdown import MarkdownParagraph
        from textual.widgets import Checkbox
        from textual.geometry import Region

        begin = time.monotonic_ns()
        app = self._app
        screen = app.screen
        if self._asyncio_log_handler is not None and not self._diagnostic_tree_logged:
            self._diagnostic_tree_logged = True
            app.log("Isolated diagnostic: native widget tree", features=sorted(app.features),
                    devtools_connected=app._is_devtools_connected,
                    slow_callback_ms=self._loop.slow_callback_duration * 1000)
            app.log(screen.tree)
        rows = []
        for widget, (region, clip) in screen._compositor.visible_widgets.items():
            if isinstance(widget, (SideBar, SideBarToggle, SidebarResizeHandle, SessionLabel, SessionsTabs, CommsRow, HistoryWindow, HistoryEdge, MarkdownParagraph, Checkbox, PromptTextArea, TranscriptFragmentView)):
                visible = region.intersection(clip).intersection(app.size.region)
                if not visible:
                    continue
                row = {"kind": type(widget).__name__, "id": widget.id, "rect": list(visible)}
                if isinstance(widget, CommsRow):
                    row["object_id"] = id(widget)
                    row["channel_roster"] = any(isinstance(node, CommsSidebar) for node in widget.ancestors)
                if isinstance(widget, SideBarToggle):
                    bar = widget.query_ancestor(SideBar)
                    row.update(sidebar=bar.id, collapsed=bar.collapsed)
                if isinstance(widget, SidebarResizeHandle):
                    bar = widget.query_ancestor(SideBar)
                    row.update(resize_sidebar=bar.id, right=bar.right,
                               width_percent=app.sidebar_layout.get(bar.id).width_percent)
                if isinstance(widget, ThreadRow):
                    row.update(target=widget.target_name, mode=widget.mode_name, row_kind=widget.kind)
                elif isinstance(widget, CommsRow):
                    row.update(target=widget.target_name, row_kind=widget.kind)
                if isinstance(widget, Checkbox):
                    row["checked"] = widget.value
                if isinstance(widget, TranscriptFragmentView):
                    row["message_category"] = widget.message_category.value
                if isinstance(widget, (HistoryWindow, SessionsTabs)):
                    row.update(scroll_y=widget.scroll_y, max_scroll_y=widget.max_scroll_y,
                               scroll_x=widget.scroll_x, max_scroll_x=widget.max_scroll_x)
                if isinstance(widget, HistoryWindow):
                    row["follows_tail"] = widget.follows_tail
                rows.append(row)
        histories = [{"loading": history._loading, "fragments": history.fragment_count,
                      "has_older": history.has_older, "has_newer": history.has_newer,
                      "pages": [{"before": str(page.page.before), "after": str(page.page.after),
                                 "text_sha256": sha256(json.dumps([TranscriptCodec.encode(event)
                                                                 for event in page.page.events],
                                                                sort_keys=True, default=str).encode()).hexdigest(),
                                 "start": page.start, "stop": page.stop} for page in history.pages]}
                     for history in screen.query(TranscriptHistory)]
        for history, summary in zip(screen.query(TranscriptHistory), histories):
            buffer = getattr(history, "_page_buffer", None)
            if buffer is not None:
                summary["buffer"] = {"ready": sum(key.scope is buffer.scope for key in buffer.runtime._ready),
                                     "pending": sum(key.scope is buffer.scope for key in buffer.runtime._pending),
                                     "retained_bytes": sum(size for key, (_, size) in buffer.runtime._ready.items()
                                                           if key.scope is buffer.scope)}
        data = {"ns": time.monotonic_ns(), "mode": app.current_mode, "screen": type(screen).__name__,
                "size": list(app.size), "tabs": [(tab.mode_name, tab.title) for tab in app.open_tabs],
                "histories": histories, "pid": os.getpid(), "widgets": rows,
                "mouse_captured": app.mouse_captured is not None,
                "presentation_policy": {
                    "retain_inactive_presentation": screen.RETAIN_INACTIVE_PRESENTATION,
                    "retain_inactive_paint": getattr(screen, "RETAIN_INACTIVE_PAINT", None),
                },
                "diagnostics": {"features": sorted(app.features),
                                "decorated_dispatch_counts": dict(dispatch_counts),
                                "devtools_connected": app._is_devtools_connected,
                                "asyncio_debug": self._loop.get_debug(),
                                "slow_callback_ms": self._loop.slow_callback_duration * 1000},
                "gc": {"enabled": gc.isenabled(), "thresholds": gc.get_threshold(), "counts": gc.get_count(),
                       "stats": gc.get_stats(), "pause_on_scroll": app.PAUSE_GC_ON_SCROLL}}
        conversation = screen.query_one_optional(Conversation)
        if conversation is not None:
            agent = conversation.agent
            data["conversation"] = {
                "agent_ready": conversation.agent_ready,
                "loading": bool(conversation.query(ThreadLoading)),
                "content_blocks": len(conversation.contents.children),
                "connected": getattr(agent, "_connected_ok", None),
                "visible_categories": sorted(category.value for category in conversation.visible_categories),
                "filter_pending": any(history._loading or history._filter_scanning or history._advancing
                                      for history in conversation.query(TranscriptHistory)),
                "errors": [{"kind": type(widget).__name__,
                            "text": str(getattr(widget, "source", getattr(widget, "content", "")))[:600]}
                           for widget in conversation.query(".-error")],
            }
            if os.environ.get("TOAD_VALIDATION_FILTER_PROBE"):
                data["conversation"]["draft_text"] = conversation.prompt.text
        preparation = getattr(app, "preparation", None)
        if preparation is not None:
            data["preparation"] = {"hits": preparation.hits, "misses": preparation.misses,
                                   "shared": preparation.shared, "entries": len(preparation._ready),
                                   "retained_bytes": preparation.retained_bytes}
        chat = screen.query_one_optional(CommsChatView)
        if chat is not None:
            data["channel_history"] = {"initialized": chat._history_initialized,
                                       "refreshing": chat._refresh_lock.locked(),
                                       "count": len(chat._history),
                                       "text_sha256": sha256(json.dumps([(message.seq, message.body)
                                                                          for message, _ in chat._history]).encode()).hexdigest()}
        Path(os.environ["TOAD_VALIDATION_SNAPSHOT"]).write_text(json.dumps(data) + "\n")
        record("snapshot", begin_ns=begin, duration_ms=(time.monotonic_ns()-begin)/1e6)

    def close(self):
        if self._focused_profiler is not None:
            self._toggle_focused_profile()
        self._running_observer = False
        gc.callbacks.remove(self._gc)
        super().close()
        if self._asyncio_log_handler is not None:
            logging.getLogger("asyncio").removeHandler(self._asyncio_log_handler)
            self._asyncio_log_handler.close()
        Path(os.environ["TOAD_VALIDATION_TRACE"]).write_text(json.dumps(list(records)) + "\n")
