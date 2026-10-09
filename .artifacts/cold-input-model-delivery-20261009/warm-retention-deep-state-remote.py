import os as _capture_os, json as _capture_json, time as _capture_time, traceback as _capture_traceback
with _capture_os.fdopen(_capture_os.open('/home/ts/wt/toad-sidebar-context-pointer-20261006/.artifacts/cold-input-model-delivery-20261009/warm-retention-deep-state-remote-entered.json', _capture_os.O_WRONLY | _capture_os.O_CREAT | _capture_os.O_EXCL, 0o600), 'w') as _capture_output:
    _capture_json.dump({'pid': _capture_os.getpid(), 'entered_ns': _capture_time.time_ns()}, _capture_output)
try:
    import importlib.util as _capture_import
    import sys as _capture_sys
    if 'sidebar_validation_driver' not in _capture_sys.modules:
        _spec = _capture_import.spec_from_file_location('sidebar_validation_driver', '/home/ts/wt/toad-sidebar-context-pointer-20261006/tools/performance/sidebar_validation_driver.py')
        _module = _capture_import.module_from_spec(_spec)
        _capture_sys.modules[_spec.name] = _module
        _spec.loader.exec_module(_module)
    _spec = _capture_import.spec_from_file_location('capture_state', '/home/ts/wt/toad-sidebar-context-pointer-20261006/tools/performance/capture_state.py')
    _module = _capture_import.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    _module.capture(expected_pid=2633414, output_prefix='/home/ts/wt/toad-sidebar-context-pointer-20261006/.artifacts/cold-input-model-delivery-20261009/warm-retention-deep-state-state', wait_history_seconds=0, wait_interval=0.1, wait_history_thread=None, frame_trace=True, install_frame_trace=False, scroll_travel_output=None, frames_only=False, runtime_only=False)
except BaseException:
    _capture_error = {'error': _capture_traceback.format_exc()}
    for _capture_path in ['/home/ts/wt/toad-sidebar-context-pointer-20261006/.artifacts/cold-input-model-delivery-20261009/warm-retention-deep-state-state']:
        if _capture_os.path.exists(_capture_path + '.json'):
            continue
        try:
            _capture_fd = _capture_os.open(_capture_path + '-error.json', _capture_os.O_WRONLY | _capture_os.O_CREAT | _capture_os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with _capture_os.fdopen(_capture_fd, 'w') as _capture_output:
            _capture_json.dump(_capture_error, _capture_output)
    raise
