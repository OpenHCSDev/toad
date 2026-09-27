"""Read a mapped X11 window without moving, focusing, or sending input to it."""

import argparse
from pathlib import Path
from Xlib import X, display
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--window", type=lambda value: int(value, 0), required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
connection = display.Display()
window = connection.create_resource_object("window", args.window)
geometry = window.get_geometry()
image = window.get_image(0, 0, geometry.width, geometry.height, X.ZPixmap, 0xFFFFFFFF)
Image.frombytes("RGB", (geometry.width, geometry.height), image.data, "raw", "BGRX").save(args.output)
connection.close()
print({"width": geometry.width, "height": geometry.height, "path": str(args.output)})
