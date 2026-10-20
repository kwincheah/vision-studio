"""The application icon exists in every format that needs it and is wired into both front ends and the build."""
import os

import pytest

from vm_clone import app_icon

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def test_icon_files_exist_and_the_ico_has_every_size():
    from PIL import Image
    for path in (app_icon.ICON_PNG, app_icon.ICON_ICO, os.path.join(app_icon.ASSETS, "app_icon.svg"), os.path.join(ROOT, "qml", "images", "app_icon.svg")):
        assert os.path.getsize(path) > 500, path
    ico = Image.open(app_icon.ICON_ICO)
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(ico.info["sizes"])
    png = Image.open(app_icon.ICON_PNG)
    assert png.size == (512, 512) and png.mode == "RGBA" and png.getpixel((0, 0))[3] == 0, "rounded corners stay transparent"
    assert png.getpixel((256, 256))[3] == 255


def test_the_qml_copy_matches_the_source_svg():
    assert read(os.path.join("qml", "images", "app_icon.svg")) == read(os.path.join("vm_clone", "assets", "app_icon.svg"))


def test_qicon_loads_and_install_sets_it_on_the_application():
    pytest.importorskip("PyQt6.QtGui")
    from PyQt6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    icon = app_icon.load_icon()
    assert not icon.isNull() and icon.availableSizes()
    app_icon.install(app)
    assert not app.windowIcon().isNull()


def test_both_front_ends_install_the_icon():
    assert "install_icon(app)" in read(os.path.join("vm_clone", "qml_app.py"))
    assert "install_icon(app)" in read("main.py")


def test_the_build_uses_the_icon():
    assert "icon='vm_clone/assets/app_icon.ico'" in read("ApexVisionStudio.spec")
    assert "('vm_clone/assets', 'vm_clone/assets')" in read("ApexVisionStudio.spec")
    iss = read("installer_setup.iss")
    assert ("SetupIconFile=vm_clone" + chr(92) + "assets" + chr(92) + "app_icon.ico") in iss and "UninstallDisplayIcon=" in iss
    assert "app_icon.svg" in read(os.path.join("qml", "ApexVision.qrc"))


def test_the_toolbar_shows_the_icon_instead_of_a_text_glyph():
    assert "app_icon.svg" in read(os.path.join("qml", "screens", "MainScreen.qml"))
