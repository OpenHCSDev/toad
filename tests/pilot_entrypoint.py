"""Execute a pilot in its private network namespace, with loopback available."""

import fcntl
from pathlib import Path
import runpy
import socket
import struct
import sys


def main() -> None:
    # External Linux interface protocol. Only the private loopback interface
    # exists, so local provider fixtures work and real providers are unreachable.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as interface:
        request = struct.pack('16sH', b'lo', 0)
        flags = struct.unpack('16sH', fcntl.ioctl(interface, 0x8913, request))[1]
        fcntl.ioctl(interface, 0x8914, struct.pack('16sH', b'lo', flags | 1))
    path = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(path.parent))
    sys.argv = [str(path)]
    runpy.run_path(str(path), run_name='__main__')


if __name__ == '__main__':
    main()
