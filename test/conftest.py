from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "qgis: tests that require a QGIS/PyQGIS runtime")
