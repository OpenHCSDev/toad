"""Read-only DTO capture of an authorized live Toad; no owner RPCs or UI input."""

def capture(*, expected_pid, output_prefix, wait_history_seconds=0, wait_interval=.1,
            wait_history_thread=None, frame_trace=False, install_frame_trace=False,
            frames_only=False, scroll_travel_output=None):
    import asyncio
    from collections import Counter
    from dataclasses import asdict
    import json
    import os
    import pickle
    import sys
    import threading
    import time
    import traceback
    from textual._context import active_app
    from textual.geometry import Offset
    from toad.widgets.conversation import CursorContainer, Conversation
    from toad.widgets.history_anchor import HistoryWindow
    from toad.widgets.prompt import PromptTextArea
    from toad.navigation_target import ChannelTarget
    from toad.widgets.comms_sidebar import CommsRow, ThreadRow
    from toad.widgets.comms_menu import ContextMenuItem
    from toad.widgets.session_tabs import SessionLabel
    from toad.widgets.tool_call import ToolCall
    from toad.transcript_source_preparation import TranscriptSourcePreparation
    from toad.widgets.transcript_history import TranscriptHistory
    from toad.mounted_message_history import MountedMessageHistory
    from toad.transcript_state import WorkingTranscript

    prefix = str(output_prefix)
    started = time.monotonic_ns()

    def write_json(path, data):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(data, output, indent=2, default=str)

    try:
        if os.getpid() != expected_pid:
            raise RuntimeError("Unexpected capture process")
        app = active_app.get(None)
        if app is None:
            for task in asyncio.all_tasks():
                app = task.get_context().get(active_app, None)
                if app is not None:
                    break
        if app is None:
            raise RuntimeError("No application context")
        if not app._mounted_event.is_set() or install_frame_trace or scroll_travel_output is not None:
            async def acquire_and_capture():
                try:
                    await app._mounted_event.wait()
                    if scroll_travel_output is not None:
                        import importlib.util
                        from pathlib import Path
                        spec = importlib.util.spec_from_file_location(
                            "scroll_travel_observation", Path(__file__).with_name("scroll_travel_observation.py"))
                        observer = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(observer)
                        observer.install(expected_pid=expected_pid, output=scroll_travel_output)
                    if install_frame_trace:
                        from sidebar_validation_driver import ValidationDriver
                        await ValidationDriver.observe_application_frames(app).wait()
                    capture(expected_pid=expected_pid, output_prefix=output_prefix,
                            wait_history_seconds=wait_history_seconds, wait_interval=wait_interval,
                            wait_history_thread=wait_history_thread, frame_trace=frame_trace,
                            frames_only=frames_only)
                except Exception:
                    write_json(prefix + "-error.json", {"error": traceback.format_exc()})

            app.run_worker(acquire_and_capture(), name="capture-mount-acquisition",
                           group="capture-mount-acquisition")
            return
        if frame_trace:
            from sidebar_validation_driver import ValidationDriver, record, records
            if frames_only:
                record("frame_trace_exported", pid=expected_pid, capacity=records.maxlen)
                write_json(prefix + "-frames.json", list(records.copy()))
                write_json(prefix + ".json", {"pid": expected_pid, "scope": "driver frame trace only"})
                return
        if wait_history_seconds:
            from toad.frame_presentation import FrameFlush

            if not wait_history_thread:
                raise ValueError("Visible-history waiting requires the intended thread")

            def visible_history_ready():
                view = app.selected_session
                if view is None or view.channels_context()[0] != wait_history_thread:
                    return False
                if not app.workspace_sessions.source.shown(view):
                    return False
                window = view.query_one_optional(HistoryWindow)
                # HistoryWindow's native tree fence owns frame publication.
                # Its async history lock may also serialize work after a
                # committed frame; holding it doesn't revoke that frame.
                if window is None or window.history_mutating():
                    return False
                screen = window.screen
                visible = screen._compositor.visible_widgets
                return (screen.is_current and window in visible
                        and any(history in visible and history.pages for history in window.histories)
                        and any(body in visible and body.body_ready for body in window.document_viewport.owners)
                        and window.document_viewport.visible_bodies_ready
                        and screen.frame_presentation.ready)

            async def wait_and_capture():
                try:
                    async with asyncio.timeout(wait_history_seconds):
                        while True:
                            if visible_history_ready():
                                written = asyncio.get_running_loop().create_future()

                                def acknowledge():
                                    if not written.done():
                                        written.set_result(None)

                                app.call_after_refresh(
                                    lambda: FrameFlush.for_driver(app._driver).submit(acknowledge))
                                await written
                                if visible_history_ready():
                                    write_json(prefix + "-wait.json", {
                                        "pid": expected_pid, "mode": app.selected_mode,
                                        "thread": app.selected_session.channels_context()[0],
                                        "elapsed_ms": (time.monotonic_ns() - started) / 1e6,
                                        "visible_saved_history_written": True,
                                    })
                                    capture(expected_pid=expected_pid, output_prefix=output_prefix,
                                            frame_trace=frame_trace)
                                    return
                            # One bounded diagnostic task observes native owners;
                            # no repeated attachment, exported snapshots or model reads.
                            await asyncio.sleep(wait_interval)
                except Exception:
                    write_json(prefix + "-error.json", {"error": traceback.format_exc()})
                    # Preserve the original resource/scene census at failure.
                    # The error still fails the marker; no predicate is relaxed.
                    capture(expected_pid=expected_pid, output_prefix=prefix + "-failure",
                            frame_trace=frame_trace)

            asyncio.create_task(wait_and_capture(), name="toad-authorized-visible-history-wait")
            return
        if frame_trace:
            record("frame_trace_exported", pid=expected_pid, capacity=records.maxlen)
            write_json(prefix + "-frames.json", list(records.copy()))
        namespace = vars(app)
        stacks = tuple((name, (view,)) for name, view in app.workspace_sessions.views.items())
        payload = {"schema": 1, "views": [], "sidebar_snapshot": namespace.get("_sidebar_snapshot")}
        metadata = {"schema": 1, "pid": os.getpid(), "captured_ns": time.time_ns(), "python": sys.version,
                    "current_mode": app.selected_mode, "open_tab_order": list(app.tab_order.names),
                    "source_modules": {name: getattr(sys.modules.get(name), "__file__", None)
                                       for name in ("toad", "textual", "agent_comms")},
                    "registry_size": len(app._registry), "views": [], "truncated": False,
                    "capture_scope": "view state, loaded pages/live block sources, cached sidebar DTO; not process memory"}

        def node_identity(node):
            return {"object_id": id(node), "class": type(node).__name__,
                    "module": type(node).__module__, "id": node.id,
                    "parent_object_id": id(node.parent) if node.parent is not None else None}

        # Observe committed native maps, not geometry getters that can force a
        # reflow and replace the evidence of a bad screen crop during capture.
        screen = app.screen
        compositor = screen._compositor
        frame = vars(screen).get("frame_presentation")
        metadata["screen"] = {
            **node_identity(screen), "current_mode": app.current_mode,
            "focused": None if screen.focused is None else {
                **node_identity(screen.focused),
                "ancestors": [node_identity(node) for node in screen.focused.ancestors_with_self],
            },
            "selected_mode": app.selected_mode, "is_current": screen.is_current,
            "scroll_offset": tuple(screen.scroll_offset),
            "max_scroll": [screen.max_scroll_x, screen.max_scroll_y],
            "virtual_size": tuple(screen.virtual_size),
            "size": tuple(screen.size),
            "layout_required": screen._layout_required,
            "scroll_required": screen._scroll_required,
            "repaint_required": screen._repaint_required,
            "dirty_widgets": [node_identity(node) for node in screen._dirty_widgets],
            "batch_count": app._batch_count,
            "atomic_mode_switch": app._atomic_mode_switch,
            "frame": None if frame is None else {
                "state": type(frame.state).__name__, "ready": frame.ready,
                "presented": frame.presented.is_set(), "deferred_callbacks": len(frame.callbacks)},
        }
        metadata["compositor"] = {
            "root": node_identity(compositor.root) if compositor.root is not None else None,
            "size": tuple(compositor.size),
            "full_map_invalidated": compositor._full_map_invalidated,
            "arranging": compositor._arranging,
            "dirty_regions": [tuple(region) for region in compositor._dirty_regions],
            "subtree_cache_entries": len(compositor._subtree_geometry),
            "layers_cached": compositor._layers is not None,
            "visible_layers_cached": compositor._layers_visible is not None,
            "cuts_cached": compositor._cuts is not None,
            "maps": {},
        }
        metadata["navigation_targets"] = {"threads": [], "channels": [], "tabs": [], "widgets": []}
        # The public owner handles full-layout and partial-layout publication.
        # _visible_map alone is only the optional partial-layout representation.
        visible_regions = compositor.visible_widgets

        def navigation_target(node, region, name):
            cell = Offset(*(int(value) for value in region.center))
            hit = app.screen.get_widget_at(*cell)[0]
            if hit is None or node not in hit.ancestors_with_self:
                return None
            return {**node_identity(node), "name": name, "region": tuple(region),
                    "focus_target": {"widget": node_identity(node), "cell": tuple(cell)}}

        for node, (native_region, native_clip) in visible_regions.items():
            region = native_region.intersection(native_clip)
            if not region:
                continue
            if target := navigation_target(node, region, node.id or type(node).__name__):
                if isinstance(node, ContextMenuItem):
                    target["action"] = node.action
                metadata["navigation_targets"]["widgets"].append(target)
            if isinstance(node, ThreadRow):
                if target := navigation_target(node, region, node.target_name):
                    metadata["navigation_targets"]["threads"].append(target)
            if isinstance(node, CommsRow) and isinstance(node.target, ChannelTarget):
                if target := navigation_target(node, region, node.target_name):
                    metadata["navigation_targets"]["channels"].append(target)
            if isinstance(node, SessionLabel):
                if target := navigation_target(node, region, node.id):
                    metadata["navigation_targets"]["tabs"].append(target)
        for name, mapping in (("full", compositor._full_map), ("visible", compositor._visible_map)):
            metadata["compositor"]["maps"][name] = None if mapping is None else {
                "count": len(mapping), "truncated": len(mapping) > 50000,
                "nodes": [{**node_identity(node),
                           "geometry": {field: tuple(value) for field, value in geometry._asdict().items()}}
                          for node, geometry in tuple(mapping.items())[:50000]],
            }
        payload["session_details"] = {mode: asdict(details) for mode, details in app.session_tracker.sessions.items()}
        for name in ("sidebar_state", "sidebar_layout"):
            model = namespace.get(name)
            if model is not None:
                payload[name] = dict(model.placements) if name == "sidebar_layout" else asdict(model)
        metadata["theme"] = namespace.get("_reactive_theme")
        metadata["terminal_geometry"] = None
        if os.isatty(sys.__stdin__.fileno()):
            import fcntl
            import struct
            import termios
            metadata["terminal_geometry"] = struct.unpack(
                "HHHH", fcntl.ioctl(sys.__stdin__.fileno(), termios.TIOCGWINSZ, bytes(8)))
        try:
            metadata["size"] = tuple(app.size)
        except Exception:
            metadata["size"] = None
        total_nodes = 0
        closed_watch_paths = Counter()
        widget_classes = Counter()
        for mode, stack in stacks:
            for screen in stack:
                fields = vars(screen)
                view = {"mode": mode, "screen_class": type(screen).__name__,
                        "identity": {key: fields.get(key) for key in (
                            "_coordination_root", "_comms_thread", "_agent_session_id", "_agent_session_title",
                            "owner_mode", "me", "target", "kind", "recovery_root", "_reactive_project_path")},
                        "history_pages": [], "history_windows": [], "drafts": [], "live_blocks": [], "bars": [], "contents": []}
                if fields.get("_thread_sidebar_state") is not None:
                    view["thread_sidebar_state"] = asdict(fields["_thread_sidebar_state"])
                pending = [screen]
                while pending:
                    node = pending.pop()
                    total_nodes += 1
                    if total_nodes > 50000:
                        metadata["truncated"] = True
                        pending.clear()
                        break
                    data = vars(node)
                    if isinstance(node, Conversation) and node.agent is not None:
                        agent = node.agent
                        mode = agent.current_mode
                        view["agent_configuration"] = {
                            "agent_object_id": id(agent), "session_id": agent.session_id,
                            "model": agent.configuration.model.current,
                            "thinking": agent.configuration.thinking.current,
                            "mode": mode.id if mode is not None else None,
                            "rendered_label": node.agent_info.plain,
                            "context_measurement": asdict(agent.context_measurement)
                                if agent.context_measurement.available else {"unavailable": agent.context_measurement.reason},
                        }
                    kind = type(node).__name__
                    widget_classes[kind] += 1
                    children = data.get("_nodes")
                    if children is not None:
                        pending.extend(tuple(children._nodes))
                    for attribute, watchers in data.get("__watchers", {}).items():
                        for subscriber, callback in tuple(watchers):
                            if subscriber._closed:
                                closed_watch_paths[(kind, attribute, type(subscriber).__name__)] += 1
                    if kind == "Conversation":
                        view["visible_categories"] = tuple(data.get("_reactive_visible_categories", ()))
                        view["goal"] = data.get("_reactive_goal")
                        view["goal_execution"] = data.get("_reactive_goal_execution")
                    if kind == "ContextExplorer":
                        from textual.widgets import Tree, TextArea, Static
                        tree = node.query_one("#context-tree", Tree)
                        detail = node.query_one("#context-detail", TextArea)
                        context_nodes = []
                        for model in node._context_nodes.values():
                            target = None
                            label_region = (tree._get_label_region(model._line)
                                            if tree._get_node(model._line) is model else None)
                            geometry = visible_regions.get(tree)
                            if label_region is not None and geometry is not None:
                                region = label_region.translate(
                                    tree.content_region.offset - tree.scroll_offset
                                ).intersection(geometry[1])
                                if region:
                                    target = navigation_target(tree, region, model.data.key)
                            context_nodes.append({"key": model.data.key,
                                                  "label": model.label.plain,
                                                  "model_type": type(model.data).__name__,
                                                  "expanded": model.is_expanded,
                                                  "target": target})
                        view["context"] = {
                            "owner": node.owner, "root": node.wire_root,
                            "native_present": node._native is not None,
                            "status": str(node.query_one(".context-status", Static).content),
                            "detail": detail.text,
                            "selected": node.intent.selected.key if node.intent.selected is not None else None,
                            "query": node.intent.query,
                            "clipboard": app.clipboard,
                            "maximized": node.screen.maximized is detail,
                            "nodes": context_nodes,
                        }
                    if isinstance(node, PromptTextArea):
                        geometry = visible_regions.get(node)
                        focus_target = None
                        if geometry is not None:
                            native_region, native_clip = geometry
                            region = native_region.intersection(native_clip)
                            if region:
                                cell = Offset(*(int(value) for value in region.center))
                                if node.screen.get_focusable_widget_at(*cell) is node:
                                    focus_target = {"widget": node_identity(node), "cell": tuple(cell)}
                        view["drafts"].append({"object_id": id(node), "lines": tuple(node.text.split("\n")),
                                               "selection": tuple(tuple(point) for point in node.selection),
                                               "focus_target": focus_target,
                                               "region": tuple(geometry[0]) if geometry is not None else None})
                    if kind == "Contents" and type(node).__module__ == "toad.widgets.conversation":
                        for child in tuple(children._nodes) if children is not None else ():
                            child_data = vars(child)
                            child_kind = type(child).__name__
                            record = {"kind": child_kind, "id": child_data.get("_id")}
                            if child_kind == "TranscriptHistory":
                                record["pages"] = tuple((page.page, page.start, page.stop) for page in tuple(child_data.get("pages", ())))
                            elif isinstance(child, ToolCall):
                                assert child.tool_call is not None
                                record["tool_call"] = child.tool_call.call.model_dump(mode="json", by_alias=True)
                                record["expanded"] = child.expanded
                            else:
                                record["text"] = next((child_data[key] for key in ("_markdown", "content", "source", "text", "_text", "_source")
                                                       if isinstance(child_data.get(key), str)), None)
                                for key in ("sender", "target", "route", "show_header", "show_divider", "sequence", "_message_category"):
                                    if key in child_data:
                                        record[key] = child_data[key]
                            view["contents"].append(record)
                    if isinstance(node, TranscriptSourcePreparation):
                        history = {
                            "object_id": id(node),
                            "class": kind,
                            "pages": (),
                            "generation": node._generation,
                            "source_state": type(node._source_state).__name__,
                            "has_newer": node.has_newer,
                        }
                        if isinstance(node._source_state, WorkingTranscript):
                            history["pending_request"] = type(node._source_state.pending_request).__name__
                        if isinstance(node, TranscriptHistory):
                            history["through"] = node.through
                            history["pages"] = tuple((page.page, page.start, page.stop) for page in node.pages)
                        if isinstance(node, MountedMessageHistory):
                            # Wire records are original messages, never native
                            # transcript pages or widgets masquerading as DTOs.
                            view["wire_history"] = tuple(message for message, _widget in node.rows)
                        view["history_pages"].append(history)
                    if isinstance(node, HistoryWindow):
                        window = {**node_identity(node), **{key: data.get(key) for key in (
                            "_reactive_scroll_y", "_reactive_scroll_x", "_is_anchored", "_anchor_released")}}
                        geometry = visible_regions.get(node)
                        window["region"] = tuple(geometry[0]) if geometry is not None else None
                        window["focus_target"] = None
                        cursor = next(iter(node.query(CursorContainer)), None)
                        cursor_geometry = visible_regions.get(cursor)
                        if geometry is not None and cursor_geometry is not None:
                            cursor_region, cursor_clip = cursor_geometry
                            region = cursor_region.intersection(cursor_clip).intersection(geometry[0])
                            if region:
                                cell = Offset(*(int(value) for value in region.center))
                                native_screen = node.screen
                                hit, _ = native_screen.get_widget_at(*cell)
                                focusable = native_screen.get_focusable_widget_at(*cell)
                                if hit is cursor and focusable is node:
                                    window["focus_target"] = {"widget": node_identity(cursor), "cell": tuple(cell)}
                        virtual_size = data.get("_reactive_virtual_size")
                        window["_reactive_virtual_size"] = tuple(virtual_size) if virtual_size is not None else None
                        window["scroll_y"] = node.scroll_y
                        window["maximum"] = node.max_scroll_y
                        window["follows_tail"] = node.follows_tail
                        window["history_lock_held"] = node.history_lock.locked()
                        window["restoring"] = node._restoring
                        window["anchor"] = (node_identity(node.history_anchor.widget)
                                            if node.history_anchor is not None else None)
                        window["layout_ready"] = (node.history_layout_ready.is_set()
                                                  if node.history_layout_ready is not None else None)
                        manager = data.get("document_viewport")
                        if manager is not None:
                            visible = visible_regions
                            owners = tuple(manager.owners)
                            roots = tuple(manager.body_roots())
                            exposed = [index for index, body in enumerate(roots) if body in visible]
                            ready_runway = {}
                            if exposed:
                                for side, neighbors in (
                                    ("before", reversed(roots[:min(exposed)])),
                                    ("after", iter(roots[max(exposed) + 1:])),
                                ):
                                    rows = 0
                                    for body in neighbors:
                                        if not body.body_ready:
                                            break
                                        rows += body.measured_rows
                                    ready_runway[side] = rows
                            outer = tuple(body for body in owners
                                          if not any(parent in manager.owners for parent in body.ancestors))
                            window["body_resources"] = {
                                "budget": asdict(manager.budget),
                                "runway": {
                                    "requested_rows": manager.lookahead.ahead_rows(node.size.height),
                                    "baseline_rows": manager.budget.runway_rows(node.size.height),
                                    "measured_body_rows": manager.visible_body_rows,
                                    "admitted_items": manager.lookahead.admission(manager.budget, node.size.height),
                                    "ready_rows": ready_runway,
                                    "demand": type(manager.lookahead.demand).__name__,
                                    "travel_rows": manager.lookahead.travel_rows,
                                    "foreground_delivery_seconds": manager.lookahead.delivery_seconds,
                                },
                                "widget_limit": manager.budget.widget_limit(node.size.height),
                                "source_byte_limit": node.app.preparation.max_bytes,
                                "body_evictions": manager.body_evictions,
                                "pending": manager._pending,
                                "outer_owner_count": len(outer),
                                "outer_materialized_widgets": sum(body.materialized_widget_count
                                                                   for body in outer),
                                "outer_materialized_source_bytes": sum(body.retained_source_bytes
                                                                        for body in outer if not body.body_dormant),
                                "registered": len(owners),
                                "dormant": sum(body.body_dormant for body in owners),
                                "visible": sum(body in visible for body in owners),
                                "visible_dormant": sum(body.body_dormant for body in owners if body in visible),
                                "reconciling": manager._running,
                                "suspended": manager._suspended,
                                "frame_admitted": manager.accepts_frame(),
                                "owners": [{**node_identity(body), "ready": body.body_ready,
                                            "dormant": body.body_dormant, "visible": body in visible,
                                            "measured_rows": body.measured_rows,
                                            "retained_widget_count": body.retained_widget_count,
                                            "native_widget_count": body.materialized_widget_count,
                                            "retained_source_bytes": body.retained_source_bytes,
                                            "measurement": {
                                                "state": type(body._body_measurement).__name__,
                                                "width": body._body_measurement.width,
                                                "rows": body._body_measurement.rows,
                                                "widgets": body._body_measurement.widgets,
                                                "paint_bytes": body.retained_paint_bytes}}
                                           for body in owners],
                            }
                        view["history_windows"].append(window)
                    if data.get("_id") in {"channels-sidebar", "thread-sidebar"}:
                        view["bars"].append({"id": data["_id"], "collapsed": data.get("_reactive_collapsed"),
                                             "right": data.get("right")})
                    if kind in {"AgentResponse", "AgentThought", "UserInput", "IncomingMessage", "CoordinationContext"}:
                        text = next((data[key] for key in ("_markdown", "source", "text", "_text", "_source")
                                     if isinstance(data.get(key), str)), None)
                        if text is not None:
                            view["live_blocks"].append({"kind": kind, "text": text, "route": data.get("route"),
                                                        "parent_class": type(node.parent).__name__})
                payload["views"].append(view)
                metadata["views"].append({"mode": mode, "screen_class": view["screen_class"],
                                          "identity": view["identity"], "history_pagers": len(view["history_pages"]),
                                          "loaded_pages": sum(len(history["pages"]) for history in view["history_pages"]),
                                          "live_blocks": len(view["live_blocks"]), "drafts": len(view["drafts"]),
                                          "history_windows": view["history_windows"],
                                          "contents_kinds": dict(Counter(record["kind"] for record in view["contents"])),
                                          "visible_categories": view.get("visible_categories")})
        metadata["widget_classes"] = widget_classes.most_common()
        metadata["closed_reactive_watch_paths"] = [(list(path), count) for path, count in closed_watch_paths.most_common()]
        metadata["ui_capture_ms"] = (time.monotonic_ns()-started)/1e6
        payload["metadata"] = metadata

        def persist():
            try:
                write_json(prefix + "-metadata.json", metadata)
                fd = os.open(prefix + ".pickle", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as output:
                    pickle.dump(payload, output, protocol=5)
                metadata["payload_bytes"] = os.stat(prefix + ".pickle").st_size
                write_json(prefix + ".json", metadata)
            except Exception:
                write_json(prefix + "-error.json", {"error": traceback.format_exc()})

        threading.Thread(target=persist, name="toad-authorized-state-export", daemon=True).start()
    except Exception:
        write_json(prefix + "-error.json", {"error": traceback.format_exc()})
