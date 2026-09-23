from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

CAR_FIELDS = ("cod_imovel", "codigo_imovel", "num_car", "numero_car", "car", "cod_car")


def _coordinates_from_google_text(value: str) -> tuple[float, float] | None:
    decoded = html.unescape(str(value or ""))
    for _ in range(3):
        decoded_value = urllib.parse.unquote(decoded)
        if decoded_value == decoded:
            break
        decoded = decoded_value
    decoded = (
        decoded.replace("\\u003d", "=")
        .replace("\\u0026", "&")
        .replace("\\u002c", ",")
        .replace("\\/", "/")
    )
    patterns = (
        # Destino e marcador têm prioridade sobre o centro/viewport (@lat,lon).
        r"[?&](?:q|query|ll|destination)=(-?\d{1,2}(?:\.\d+)?)(?:,\+?|\+)(-?\d{1,3}(?:\.\d+)?)",
        r"!3d(-?\d{1,2}(?:\.\d+)?)!4d(-?\d{1,3}(?:\.\d+)?)",
        r"/(?:place|search|dir)/(?:[^/?#]+/)*(-?\d{1,2}(?:\.\d+)?)(?:,\+?|\+)(-?\d{1,3}(?:\.\d+)?)",
        r"(?:geo:|google\.navigation:q=)(-?\d{1,2}(?:\.\d+)?)(?:,\+?|\+)(-?\d{1,3}(?:\.\d+)?)",
        r"[?&]center=(-?\d{1,2}(?:\.\d+)?)(?:,\+?|\+)(-?\d{1,3}(?:\.\d+)?)",
        r"@(-?\d{1,2}(?:\.\d+)?),(-?\d{1,3}(?:\.\d+)?)",
    )
    for pattern in patterns:
        match = re.search(pattern, decoded, flags=re.IGNORECASE)
        if match:
            latitude, longitude = map(float, match.groups())
            if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                return latitude, longitude
    return None


def coordinates_from_google_maps_url(value: str) -> tuple[float, float]:
    """Extrai latitude/longitude de URLs longas ou encurtadas do Google Maps."""
    url = (value or "").strip()
    if not url:
        raise ValueError("Cole o link de compartilhamento do Google Maps.")
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not (
        host == "goo.gl"
        or host.endswith(".goo.gl")
        or host == "google.com"
        or host.endswith(".google.com")
    ):
        raise ValueError("O endereço informado não é um link do Google Maps.")

    coordinates = _coordinates_from_google_text(url)
    if coordinates:
        return coordinates

    if "goo.gl" in host:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                final_url = response.geturl()
                # O endereço final descreve o ponto compartilhado. O HTML também
                # contém coordenadas de viewport e só deve ser usado como reserva.
                coordinates = _coordinates_from_google_text(final_url)
                if coordinates:
                    return coordinates
                body = response.read(1_500_000).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                raise ValueError(
                    "O Google informou que esse link curto não existe ou expirou. "
                    "Abra novamente o local no Google Maps e use Compartilhar > Copiar link."
                ) from exc
            raise ValueError(
                f"O Google Maps recusou a abertura do link (HTTP {exc.code})."
            ) from exc
        except urllib.error.URLError as exc:
            raise ValueError(
                "Não foi possível acessar o link curto. Verifique a conexão com a internet e tente novamente."
            ) from exc
        coordinates = _coordinates_from_google_text(body)
        if coordinates:
            return coordinates

    raise ValueError(
        "O link abriu, mas o Google Maps não forneceu uma coordenada reconhecível. "
        "Abra o local exato no mapa e use Compartilhar > Copiar link."
    )


from qgis_plugin_microcredito.domain.normalize import normalize_car


def formatted_car(value: str) -> str:
    code = normalize_car(value)
    if len(code) != 41:
        return value
    tail = code[9:]
    return f"{code[:2]}-{code[2:9]}-" + ".".join(
        tail[index : index + 4] for index in range(0, 32, 4)
    )


def candidate_files(directory: str | Path, car: str) -> list[Path]:
    base = Path(directory)
    if not base.is_dir():
        return []
    uf = normalize_car(car)[:2]
    files = (
        list(base.rglob("*.gpkg"))
        + list(base.rglob("*.shp"))
        + list(base.rglob("*.geojson"))
    )
    preferred = [
        path
        for path in files
        if uf
        and uf == path.parent.name.upper()
        or path.stem.upper().startswith(uf + "_")
    ]
    return preferred + [path for path in files if path not in preferred]


def find_cars_by_point(
    directory: str | Path, latitude: float, longitude: float
) -> list[dict[str, object]]:
    """Localiza imóveis do SICAR que contêm um ponto WGS84."""
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Latitude ou longitude fora do intervalo válido.")
    base = Path(directory)
    if not base.is_dir():
        raise ValueError("Selecione a pasta com os polígonos do CAR.")
    files = (
        list(base.rglob("*.gpkg"))
        + list(base.rglob("*.shp"))
        + list(base.rglob("*.geojson"))
    )
    source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    results = []
    for path in files:
        layer = QgsVectorLayer(str(path), path.stem, "ogr")
        if not layer.isValid() or not layer.crs().isValid():
            continue
        fields = {field.name().lower(): field.name() for field in layer.fields()}
        car_field = next((fields[name] for name in CAR_FIELDS if name in fields), None)
        if not car_field:
            continue
        point = QgsGeometry.fromPointXY(QgsPointXY(longitude, latitude))
        point.transform(
            QgsCoordinateTransform(
                source_crs, layer.crs(), QgsProject.instance().transformContext()
            )
        )
        request = QgsFeatureRequest().setFilterRect(point.boundingBox())
        for feature in layer.getFeatures(request):
            if feature.hasGeometry() and feature.geometry().intersects(point):
                results.append(
                    {
                        "car": str(feature[car_field]),
                        "car_normalizado": normalize_car(feature[car_field]),
                        "arquivo": str(path),
                        "fid": int(feature.id()),
                    }
                )
    unique = {
        item["car_normalizado"]: item for item in results if item["car_normalizado"]
    }
    return sorted(unique.values(), key=lambda item: str(item["car"]))


def find_car_feature(directory: str | Path, car: str):
    wanted = normalize_car(car)
    values = {wanted, formatted_car(wanted)}
    if len(wanted) == 41:
        # O GeoPackage atual do SICAR usa dois hifens e não usa pontos no UUID.
        values.add(f"{wanted[:2]}-{wanted[2:9]}-{wanted[9:]}")
    for path in candidate_files(directory, car):
        layer = QgsVectorLayer(str(path), path.stem, "ogr")
        if not layer.isValid():
            continue
        fields = {field.name().lower(): field.name() for field in layer.fields()}
        field = next((fields[name] for name in CAR_FIELDS if name in fields), None)
        if not field:
            continue
        quoted = ",".join("'" + value.replace("'", "''") + "'" for value in values)
        request = QgsFeatureRequest().setFilterExpression(f'"{field}" IN ({quoted})')
        for feature in layer.getFeatures(request):
            if normalize_car(feature[field]) == wanted and feature.hasGeometry():
                return layer, feature, path, field
    return None


def export_car_feature(
    directory: str | Path, car: str, output: str | Path
) -> Path | None:
    found = find_car_feature(directory, car)
    if not found:
        return None
    layer, feature, source_path, field = found
    properties = {name: feature[name] for name in layer.fields().names()}
    properties.update({"fonte_arquivo": str(source_path), "campo_car": field})
    collection = {
        "type": "FeatureCollection",
        "name": f"car_{normalize_car(car)}",
        "crs": {
            "type": "name",
            "properties": {"name": layer.crs().authid() or "EPSG:4674"},
        },
        "features": [
            {
                "type": "Feature",
                "properties": properties,
                "geometry": json.loads(feature.geometry().asJson()),
            }
        ],
    }
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(collection, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return destination


def add_google_satellite() -> QgsRasterLayer | None:
    name = "Google Satellite"
    existing = QgsProject.instance().mapLayersByName(name)
    if existing:
        return existing[0]
    uri = "type=xyz&url=https://mt1.google.com/vt/lyrs=s%26x%3D%7Bx%7D%26y%3D%7By%7D%26z%3D%7Bz%7D&zmax=21&zmin=0"
    layer = QgsRasterLayer(uri, name, "wms")
    if not layer.isValid():
        return None
    layer.setCustomProperty("car_microcredito/managed_basemap", True)
    QgsProject.instance().addMapLayer(layer)
    return layer
