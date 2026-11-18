"""User boundary: Carregar no mapa keeps CAR focus after real layer-tree events.

Only settings and message dialogs are isolated. CAR lookup/export, environmental
selection, the map canvas and its layer-tree bridge use their real implementations.
Rendering is disabled: these tests cover framing, not network tile availability.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsRectangle,
    QgsSettings,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.gui import QgsLayerTreeMapCanvasBridge, QgsMapCanvas
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QPushButton

from plugin import plugin
from qgis_plugin_microcredito.application.local_data_paths import (
    default_local_data_paths,
)

CAR = "MT-5100102-00000000000000000000000000000001"
CRS_BEHAVIOR_KEY = "/projections/newProjectCrsBehavior"


def settle_events() -> None:
    # Do not synchronize the bridge here: the user-facing action must do that.
    for _ in range(5):
        QApplication.processEvents()


@dataclass
class MapSession:
    window: plugin.SearchWindow
    canvas: QgsMapCanvas
    project: QgsProject
    settings: QgsSettings
    failures: list[str]
    output: Path

    def configure(self, crs_id: str, behavior: str = "UsePresetCrs") -> None:
        self.settings.setValue(CRS_BEHAVIOR_KEY, behavior, QgsSettings.Section.App)
        self.project.setCrs(QgsCoordinateReferenceSystem(crs_id))
        self.canvas.setDestinationCrs(self.project.crs())

    def click_load(self) -> None:
        self.window.car.setText(CAR)
        buttons = [
            button
            for button in self.window.findChildren(QPushButton)
            if button.text() == "Carregar no mapa"
        ]
        assert len(buttons) == 1
        assert buttons[0].isEnabled()
        buttons[0].click()
        settle_events()
        assert not self.failures, self.failures

    def assert_car_framed(self, label: str) -> None:
        view = QgsCoordinateTransform(
            self.canvas.mapSettings().destinationCrs(),
            QgsCoordinateReferenceSystem("EPSG:4326"),
            self.project.transformContext(),
        ).transformBoundingBox(self.canvas.extent())
        observation = {
            "canvas_crs": self.canvas.mapSettings().destinationCrs().authid(),
            "view_wgs84": [
                view.xMinimum(),
                view.yMinimum(),
                view.xMaximum(),
                view.yMaximum(),
            ],
            "width_degrees": view.width(),
            "height_degrees": view.height(),
            "center": [view.center().x(), view.center().y()],
            "layer_count": len(self.project.mapLayers()),
        }
        (self.output / f"{label}.json").write_text(
            json.dumps(observation, indent=2), encoding="utf-8"
        )
        # The literal source polygon spans 0.01 degrees in each direction. A
        # close view must fit it while leaving it prominent, irrespective of CRS.
        assert view.contains(QgsRectangle(-50, -10.01, -49.99, -10)), observation
        assert view.width() < 0.04 and view.height() < 0.04, observation
        assert min(view.width(), view.height()) > 0.011, observation
        assert abs(view.center().x() + 49.995) < 0.001, observation
        assert abs(view.center().y() + 10.005) < 0.001, observation
        assert self.project.mapLayersByName("Google Satellite"), observation
        assert self.canvas.layerCount() == len(self.project.mapLayers()), observation


@pytest.fixture
def map_session(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[MapSession]:
    # Short fixture names also work with OGR on Windows without long-path support.
    root = tmp_path_factory.mktemp("map")
    monkeypatch.setenv("LOCALAPPDATA", str(root / "local"))

    def private_settings(*_args: object, **_kwargs: object) -> QSettings:
        return QSettings(str(root / "prefs.ini"), QSettings.Format.IniFormat)

    monkeypatch.setattr(plugin, "QSettings", private_settings)
    settings = QgsSettings()
    section = QgsSettings.Section.App
    had_behavior = settings.contains(CRS_BEHAVIOR_KEY, section)
    old_behavior = settings.value(CRS_BEHAVIOR_KEY, section=section)

    def restore_settings() -> None:
        if had_behavior:
            settings.setValue(CRS_BEHAVIOR_KEY, old_behavior, section)
        else:
            settings.remove(CRS_BEHAVIOR_KEY, section)
        settle_events()

    with ExitStack() as resources:
        resources.callback(restore_settings)
        settings.setValue(CRS_BEHAVIOR_KEY, "UsePresetCrs", section)

        project = QgsProject.instance()
        project.clear()
        canvas = QgsMapCanvas()
        resources.callback(canvas.deleteLater)
        resources.callback(canvas.close)
        resources.callback(project.clear)
        canvas.resize(800, 600)
        canvas.setRenderFlag(False)
        canvas.show()
        settle_events()
        bridge = QgsLayerTreeMapCanvasBridge(project.layerTreeRoot(), canvas, canvas)

        def sync_project_crs() -> None:
            canvas.setDestinationCrs(project.crs())

        project.crsChanged.connect(sync_project_crs)
        resources.callback(project.crsChanged.disconnect, sync_project_crs)

        class MapIface:
            @staticmethod
            def mainWindow() -> None:
                return None

            @staticmethod
            def mapCanvas() -> QgsMapCanvas:
                return canvas

            @staticmethod
            def layerTreeCanvasBridge() -> QgsLayerTreeMapCanvasBridge:
                return bridge

        paths = default_local_data_paths()
        paths.car.mkdir(parents=True)
        (paths.car / "MT_perimetros.geojson").write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"cod_imovel": CAR},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [-50, -10],
                                        [-49.99, -10],
                                        [-49.99, -10.01],
                                        [-50, -10.01],
                                        [-50, -10],
                                    ]
                                ],
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        paths.environmental.mkdir(parents=True)
        environmental = QgsVectorLayer("Polygon?crs=EPSG:4326", "forest", "memory")
        feature = QgsFeature()
        feature.setGeometry(
            QgsGeometry.fromWkt("POLYGON ((-70 -20,-30 -20,-30 10,-70 10,-70 -20))")
        )
        assert environmental.dataProvider().addFeatures([feature])[0]
        environmental.updateExtents()
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        written = QgsVectorFileWriter.writeAsVectorFormatV3(
            environmental,
            str(paths.environmental / "florestas_publicas.gpkg"),
            project.transformContext(),
            options,
        )
        assert written[0] == QgsVectorFileWriter.WriterError.NoError, written
        failures: list[str] = []

        def capture_message(*args: object) -> QMessageBox.StandardButton:
            failures.append(str(args[-1]))
            return QMessageBox.StandardButton.Ok

        for method in ("critical", "information", "warning"):
            monkeypatch.setattr(QMessageBox, method, capture_message)
        window = plugin.SearchWindow(MapIface())
        resources.callback(window.deleteLater)
        resources.callback(window.close)
        yield MapSession(window, canvas, project, settings, failures, root)


@pytest.mark.parametrize(
    ("initial_crs", "behavior", "expected_crs"),
    [
        ("EPSG:4326", "UsePresetCrs", "EPSG:4326"),
        ("EPSG:3857", "UsePresetCrs", "EPSG:3857"),
        ("EPSG:3857", "UseCrsOfFirstLayerAdded", "EPSG:4326"),
    ],
    ids=["preset-geographic", "preset-metric", "first-layer-crs"],
)
def test_first_load_button_retains_car_focus_after_layer_tree_events(
    map_session: MapSession, initial_crs: str, behavior: str, expected_crs: str
) -> None:
    map_session.configure(initial_crs, behavior)
    assert not map_session.project.mapLayers()
    map_session.click_load()
    map_session.assert_car_framed("first-load")
    assert map_session.canvas.mapSettings().destinationCrs().authid() == expected_crs


@pytest.mark.parametrize("crs_id", ["EPSG:4326", "EPSG:3857"])
def test_load_button_focuses_car_in_open_project_and_on_repeat(
    map_session: MapSession, crs_id: str
) -> None:
    map_session.configure(crs_id)
    unrelated = QgsVectorLayer("Polygon?crs=EPSG:4326", "User layer", "memory")
    feature = QgsFeature()
    feature.setGeometry(
        QgsGeometry.fromWkt("POLYGON ((-80 -30,-75 -30,-75 -25,-80 -25,-80 -30))")
    )
    assert unrelated.dataProvider().addFeatures([feature])[0]
    unrelated.updateExtents()
    map_session.project.addMapLayer(unrelated)
    settle_events()
    map_session.click_load()
    map_session.assert_car_framed("open-project")
    first_count = len(map_session.project.mapLayers())
    map_session.click_load()
    map_session.assert_car_framed("repeat-load")
    assert len(map_session.project.mapLayers()) == first_count
    assert map_session.project.mapLayer(unrelated.id()) is unrelated
    assert map_session.canvas.mapSettings().destinationCrs().authid() == crs_id


def test_completed_map_load_does_not_reset_manual_pan_or_zoom(
    map_session: MapSession,
) -> None:
    map_session.configure("EPSG:4326")
    map_session.click_load()
    map_session.assert_car_framed("before-navigation")
    # Navigate through the public canvas API after the load has completed.
    map_session.canvas.setExtent(QgsRectangle(-48, -9.01, -47.98, -9))
    map_session.canvas.refresh()
    manual = QgsRectangle(map_session.canvas.extent())
    QTest.qWait(600)  # Includes the canvas' normal 500 ms resize refresh timer.
    settle_events()
    assert map_session.canvas.extent() == manual
    map_session.canvas.zoomByFactor(0.5)
    zoomed = QgsRectangle(map_session.canvas.extent())
    assert zoomed.width() < manual.width()
    QTest.qWait(600)
    settle_events()
    assert map_session.canvas.extent() == zoomed
