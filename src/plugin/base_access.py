"""Hold a base-edition lease for the complete user-facing consultation."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Protocol

from qgis.PyQt.QtCore import pyqtSlot
from qgis.PyQt.QtWidgets import QMessageBox

from qgis_plugin_microcredito.application.local_data_paths import LocalDataPaths
from qgis_plugin_microcredito.infrastructure.base_access import (
    BaseAccessBusy,
    read_base_access,
)


class BaseAccessWindow(Protocol):
    local_paths: LocalDataPaths


def with_base_access(operation: Callable[..., object]) -> Callable[..., object]:
    """Guard queries, map construction and reports without locking idle windows."""

    @pyqtSlot()
    @wraps(operation)
    def guarded(window: BaseAccessWindow, *args: object, **kwargs: object) -> object:
        try:
            with read_base_access(window.local_paths.root):
                return operation(window, *args, **kwargs)
        except BaseAccessBusy as exc:
            QMessageBox.warning(window, "Bases temporariamente indisponíveis", str(exc))
            return None

    return guarded
