"""Núcleo da automação de CAR para microcrédito rural."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("qgis-plugin-microcredito")
except PackageNotFoundError:
    __version__ = "0.8.0"

__all__ = ["__version__"]
