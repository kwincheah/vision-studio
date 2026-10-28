"""The one place the application version lives.

``DISPLAY`` is what people see (window titles, About, installer, release tag); ``PACKAGE`` is the same
number in the form Python packaging requires (pyproject.toml). ``tests/test_version.py`` keeps them in step.
"""
DISPLAY = "1.0.0-beta.1"
PACKAGE = "1.0.0b1"
