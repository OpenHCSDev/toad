"""Run existing mounted consumers with unrelated internet telemetry disabled."""
import runpy
import sys
from pathlib import Path


def main():
    from toad.app import ToadApp
    ToadApp.capture_event = lambda *args, **kwargs: None
    ToadApp.run_version_check = lambda *args, **kwargs: None
    target = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(target.parent))
    runpy.run_path(str(target), run_name='__main__')


if __name__ == '__main__':
    main()
