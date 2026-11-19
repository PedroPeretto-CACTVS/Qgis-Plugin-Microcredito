"""Cold application flow: the first consultation preserves projected measures."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer
from qgis.PyQt.QtWidgets import QDialog
from test_pre_analysis_window import analysis_window as analysis_window
from test_pre_analysis_window import button_named, interact_with_pre_analysis

from plugin import plugin
from plugin.analysis import EnvironmentalSource, analyze_layer


def test_first_pre_analysis_preserves_projected_area_measurements(
    analysis_window: plugin.SearchWindow, tmp_path: Path
) -> None:
    def close(dialog: QDialog) -> None:
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, close)
    target = QgsVectorLayer("Polygon?crs=EPSG:3857", "target", "memory")
    source_layer = QgsVectorLayer("Polygon?crs=EPSG:3857", "source", "memory")
    for layer in (target, source_layer):
        feature = QgsFeature()
        feature.setGeometry(
            QgsGeometry.fromWkt("POLYGON ((0 0,100 0,100 100,0 100,0 0))")
        )
        assert layer.dataProvider().addFeatures([feature])[0]
        layer.updateExtents()
    source = EnvironmentalSource(
        "synthetic", "Fonte sintetica", tmp_path / "source.gpkg", "https://example.test"
    )
    result = analyze_layer(target, source, source_layer)
    # A 100m square at the Web Mercator origin measures 0.9933 ha on GRS80.
    assert result["area_sobreposta_ha"] == pytest.approx(0.9933, abs=0.0002)
