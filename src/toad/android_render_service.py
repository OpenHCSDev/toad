"""python-for-android service entry for Toad's renderer process."""

from toad.render_socket_service import android_render_socket, serve_render_socket


def main() -> None:
    serve_render_socket(android_render_socket())


if __name__ == "__main__":
    main()

