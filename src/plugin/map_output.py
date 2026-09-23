from __future__ import annotations

from pathlib import Path

from qgis.core import (
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsFillSymbol,
    QgsGeometry,
    QgsMapRendererParallelJob,
    QgsMapSettings,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QEventLoop, QSize
from qgis.PyQt.QtGui import QColor

from .analysis import _load_layer

MAP_PALETTE = (
    ("#D41159", "Embargos ambientais"),
    ("#00A6D6", "Terras indígenas"),
    ("#8B5CF6", "Territórios quilombolas"),
    ("#009E73", "Unidades de conservação"),
    ("#0057B8", "Florestas públicas"),
    ("#FF7A00", "Desmatamento PRODES após 2020"),
)

MAP_STYLE_BY_CODE = {
    "embargos": MAP_PALETTE[0],
    "terras_indigenas": MAP_PALETTE[1],
    "territorios_quilombolas": MAP_PALETTE[2],
    "unidades_conservacao": MAP_PALETTE[3],
    "florestas_publicas": MAP_PALETTE[4],
    "desmatamento_pos_2020": MAP_PALETTE[5],
}


def _source_entry(item, index: int) -> tuple[str, str, str, str]:
    path = str(getattr(item, "path", item))
    code = str(getattr(item, "code", "") or "")
    fallback = MAP_PALETTE[index % len(MAP_PALETTE)]
    color, default_name = MAP_STYLE_BY_CODE.get(code, fallback)
    name = str(getattr(item, "name", "") or default_name)
    return path, name, code, color


def render_analysis_map(
    target_path: str | Path,
    sources: list[object],
    output: str | Path,
    include_satellite: bool = True,
    legend_entries: list[dict[str, str]] | None = None,
) -> Path | None:
    if legend_entries is not None:
        legend_entries.clear()
    target = QgsVectorLayer(str(target_path), "Imóvel analisado", "ogr")
    if not target.isValid() or target.featureCount() == 0:
        return None
    target.renderer().setSymbol(
        QgsFillSymbol.createSimple(
            {
                "color": "255,214,0,55",
                "outline_color": "20,24,31,255",
                "outline_width": "1.6",
            }
        )
    )
    layers = [target]
    extent = target.extent()
    extent.scale(1.25)
    transform_context = QgsProject.instance().transformContext()
    for index, source in enumerate(sources):
        source_path, source_name, source_code, color_hex = _source_entry(source, index)
        layer = _load_layer(Path(source_path))
        if layer.isValid():
            try:
                source_extent = QgsCoordinateTransform(
                    target.crs(), layer.crs(), transform_context
                ).transformBoundingBox(extent)
                visible_area = QgsGeometry.fromRect(source_extent)
                request = QgsFeatureRequest().setFilterRect(source_extent)
                has_visible_feature = any(
                    feature.hasGeometry()
                    and feature.geometry().intersects(visible_area)
                    for feature in layer.getFeatures(request)
                )
            except Exception:
                has_visible_feature = False
            if not has_visible_feature:
                continue
            color = QColor(color_hex)
            layer.renderer().setSymbol(
                QgsFillSymbol.createSimple(
                    {
                        "color": f"{color.red()},{color.green()},{color.blue()},92",
                        "outline_color": f"{color.red()},{color.green()},{color.blue()},255",
                        "outline_width": "1.1",
                    }
                )
            )
            layers.append(layer)
            if legend_entries is not None:
                legend_entries.append(
                    {
                        "code": source_code,
                        "label": source_name,
                        "color": color_hex,
                    }
                )
    uri = "type=xyz&url=https://mt1.google.com/vt/lyrs=s%26x%3D%7Bx%7D%26y%3D%7By%7D%26z%3D%7Bz%7D&zmax=21&zmin=0"
    if include_satellite:
        satellite = QgsRasterLayer(uri, "Google Satellite", "wms")
        if satellite.isValid():
            layers.append(satellite)
    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setExtent(extent)
    settings.setDestinationCrs(target.crs())
    settings.setOutputSize(QSize(1600, 900))
    settings.setBackgroundColor(QColor("white"))
    job = QgsMapRendererParallelJob(settings)
    loop = QEventLoop()
    job.finished.connect(loop.quit)
    job.start()
    if job.isActive():
        loop.exec_()
    image = job.renderedImage()
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination if image.save(str(destination), "PNG") else None
