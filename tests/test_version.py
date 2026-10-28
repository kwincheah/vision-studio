"""One version number: apex_vision/version.py is the source and everything else must agree with it."""
import os
import re

from apex_vision import version

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_display_and_package_versions_are_the_same_number():
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)-beta\.(\d+)", version.DISPLAY)
    assert m, "beta releases look like 1.0.0-beta.1"
    assert version.PACKAGE == f"{m[1]}.{m[2]}.{m[3]}b{m[4]}"


def test_packaging_installer_and_release_notes_follow_the_version():
    assert f'version = "{version.PACKAGE}"' in read("pyproject.toml")
    assert f'#define MyAppVersion "{version.DISPLAY}"' in read("installer_setup.iss")
    notes = f"docs/RELEASE_NOTES_v{version.DISPLAY}.md"
    assert os.path.exists(os.path.join(ROOT, notes))
    assert notes in read(".github", "workflows", "release.yml")
    assert notes in read("README.md")
    assert "prerelease: true" in read(".github", "workflows", "release.yml"), "a beta must not be published as the latest release"


def test_the_ui_shows_the_version_from_one_place():
    from apex_vision import qml_backend
    assert qml_backend.APP_VERSION == version.DISPLAY
