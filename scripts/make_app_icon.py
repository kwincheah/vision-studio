"""Render the application icon: vm_clone/assets/app_icon.svg -> app_icon.png (512) and app_icon.ico (16-256 px)."""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402
from PyQt6.QtCore import QBuffer, QIODevice  # noqa: E402
from PyQt6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PyQt6.QtSvg import QSvgRenderer  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vm_clone", "assets")
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int) -> Image.Image:
    renderer = QSvgRenderer(os.path.join(ASSETS, "app_icon.svg"))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def main() -> None:
    QGuiApplication.instance() or QGuiApplication([])
    render(512).save(os.path.join(ASSETS, "app_icon.png"))
    frames = [render(s) for s in SIZES]
    frames[-1].save(os.path.join(ASSETS, "app_icon.ico"), format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    print("wrote app_icon.png and app_icon.ico in", ASSETS)


if __name__ == "__main__":
    main()
