"""Core library adapter used by the QGIS UI."""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

CoreFunctions = tuple[
    Callable[..., sqlite3.Connection],
    Callable[..., None],
    Callable[..., list[dict[str, Any]]],
    Callable[..., dict[str, Any]],
    Callable[..., list[dict[str, Any]]],
    Callable[..., list[dict[str, Any]]],
    Callable[..., list[dict[str, Any]]],
    Callable[..., list[dict[str, Any]]],
]


def _load_core() -> CoreFunctions:
    bundled = Path(__file__).parent / "lib"
    if bundled.is_dir() and str(bundled) not in sys.path:
        sys.path.insert(0, str(bundled))
    from database.session import connect as database_connect
    from qgis_plugin_microcredito.application.geo_service import build_glebas_geojson
    from qgis_plugin_microcredito.application.query_service import (
        find_by_car,
        find_by_document,
        find_documents_by_car,
        find_mma_mcr_by_car,
        find_slave_labor_by_documents,
    )

    def connect(path: str | Path) -> sqlite3.Connection:
        return database_connect(path, readonly=True)

    def initialize(connection: sqlite3.Connection) -> None:
        pass

    return (
        connect,
        initialize,
        find_by_document,
        build_glebas_geojson,
        find_mma_mcr_by_car,
        find_documents_by_car,
        find_by_car,
        find_slave_labor_by_documents,
    )
