from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from qgis_plugin_microcredito.domain.wkt import parse_area_wkt


def _wkt_geometry(wkt: str) -> dict[str, Any]:
    return parse_area_wkt(wkt)


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
