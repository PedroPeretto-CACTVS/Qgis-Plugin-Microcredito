"""A project coordinate-operation change requires a fresh consultation."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsProject,
)
from qgis.PyQt.QtWidgets import QDialog
from test_pre_analysis_window import analysis_window as analysis_window
from test_pre_analysis_window import button_named, interact_with_pre_analysis

from plugin import plugin
from qgis_plugin_microcredito.application.local_data_paths import (
    default_local_data_paths,
)


def test_changing_project_transformations_requires_fresh_crossings(
    analysis_window: plugin.SearchWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = QgsProject.instance()
    saved_context = QgsCoordinateTransformContext(project.transformContext())

    def close(dialog: QDialog) -> None:
        button_named(dialog, "Fechar sem alterar").click()

    try:
        interact_with_pre_analysis(analysis_window, close)
        source_reads = []
        original_open = Path.open
        environmental = default_local_data_paths().environmental

        def observe_storage(path: Path, mode="r", *args, **kwargs):
            if path.parent == environmental and mode == "rb":
                source_reads.append(path.name)
            return original_open(path, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", observe_storage)
        changed = QgsCoordinateTransformContext(saved_context)
        assert changed.addCoordinateOperation(
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsCoordinateReferenceSystem("EPSG:3857"),
            "+proj=noop",
            False,
        )
        project.setTransformContext(changed)
        interact_with_pre_analysis(analysis_window, close)
        assert source_reads, (
            "O projeto mudou, mas os cruzamentos anteriores foram reutilizados."
        )
    finally:
        project.setTransformContext(saved_context)
