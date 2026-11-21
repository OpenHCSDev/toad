"""python-for-android service entry for Toad's renderer process."""

from toad.render_socket_service import android_render_socket, serve_render_socket

serve_render_socket(android_render_socket())

