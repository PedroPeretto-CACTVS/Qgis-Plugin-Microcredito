from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from typing import Any

_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")


def _parse_group(text: str, position: int = 0) -> tuple[list[Any], int]:
    result: list[Any] = []
    token: list[str] = []
    position += 1
    while position < len(text):
        char = text[position]
        if char == "(":
            child, position = _parse_group(text, position)
            result.append(child)
        elif char == ")":
            if "".join(token).strip():
                result.append("".join(token).strip())
            return result, position + 1
        elif char == ",":
            if "".join(token).strip():
                result.append("".join(token).strip())
                token = []
            position += 1
        else:
            token.append(char)
            position += 1
    raise ValueError("Geometria WKT com parênteses incompletos")


def _coordinates(items: list[Any]) -> Any:
    if items and isinstance(items[0], str):
        points: list[list[float]] = []
        for item in items:
            values = _NUMBER.findall(item)
            if len(values) >= 2:
                points.append([float(values[0]), float(values[1])])
        return points
    return [_coordinates(item) for item in items]


def _wkt_geometry(wkt: str) -> dict[str, Any]:
    upper = wkt.lstrip().upper()
    geometry_type = "MultiPolygon" if upper.startswith("MULTIPOLYGON") else "Polygon"
    start = wkt.find("(")
    if start < 0:
        raise ValueError("Geometria WKT sem coordenadas")
    nested, _ = _parse_group(wkt, start)
    return {"type": geometry_type, "coordinates": _coordinates(nested)}


def build_glebas_geojson(
    connection: sqlite3.Connection, ref_bacen: str, nu_ordem: str
) -> dict[str, Any]:
    """Reconstrói as glebas do Sicor como GeoJSON em WGS 84 (lon, lat)."""
    rows = connection.execute(
        """SELECT importacao_id, identificador, indice_gleba, indice_ponto, latitude, longitude, id_ponto
             FROM ativo_sicor_ponto_gleba
            WHERE ref_bacen = ? AND nu_ordem = ?
         ORDER BY identificador, indice_gleba, indice_ponto, id""",
        (ref_bacen, nu_ordem),
    ).fetchall()
    discarded = 0
    groups: dict[tuple[object, object], list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            discarded += 1
            continue
        groups[(row["identificador"], row["indice_gleba"])].append(
            (longitude, latitude)
        )

    features: list[dict[str, Any]] = []
    for (identifier, plot_index), coordinates in groups.items():
        cleaned: list[tuple[float, float]] = []
        for coordinate in coordinates:
            if not cleaned or cleaned[-1] != coordinate:
                cleaned.append(coordinate)
        if len(set(cleaned)) < 3:
            discarded += 1
            continue
        if cleaned[0] != cleaned[-1]:
            cleaned.append(cleaned[0])
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "ref_bacen": ref_bacen,
                    "nu_ordem": nu_ordem,
                    "identificador": identifier,
                    "indice_gleba": plot_index,
                    "total_pontos": len(cleaned) - 1,
                },
                "geometry": {"type": "Polygon", "coordinates": [cleaned]},
            }
        )
    wkt_rows = connection.execute(
        """SELECT importacao_id, indice_gleba, geometria_wkt
             FROM ativo_sicor_gleba_wkt
            WHERE ref_bacen = ? AND nu_ordem = ?
         ORDER BY indice_gleba, id""",
        (ref_bacen, nu_ordem),
    ).fetchall()
    if len({row["importacao_id"] for row in [*rows, *wkt_rows]}) > 1:
        raise ValueError(
            "Gleba presente em escopos ativos sobrepostos; revise as edições antes de analisar."
        )
    for row in wkt_rows:
        try:
            geometry = _wkt_geometry(row["geometria_wkt"])
        except (TypeError, ValueError):
            discarded += 1
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "ref_bacen": ref_bacen,
                    "nu_ordem": nu_ordem,
                    "indice_gleba": row["indice_gleba"],
                    "origem_geometria": "sicor_glebas_wkt",
                },
                "geometry": geometry,
            }
        )
    if discarded:
        raise ValueError(
            f"Geometria incompleta: {discarded} registro(s)/gleba(s) não puderam ser reconstruídos."
        )
    return {
        "type": "FeatureCollection",
        "name": f"sicor_glebas_{ref_bacen}_{nu_ordem}",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "features": features,
        "metadata": {
            "registros_lidos": len(rows) + len(wkt_rows),
            "glebas_identificadas": len(groups) + len(wkt_rows),
            "poligonos_validos": len(features),
        },
    }
