"""Validações usadas antes de promover downloads para bases de consulta."""

from __future__ import annotations

import sqlite3
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

UFS = set(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)


def validate_zip(path: str | Path) -> bool:
    with zipfile.ZipFile(path) as archive:
        if not archive.infolist() or archive.testzip() is not None:
            raise ValueError("ZIP vazio ou com erro de integridade.")
    return True


def validate_geopackage(path: str | Path, uf: str | None = None) -> bool:
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if list(connection.execute("PRAGMA quick_check")) != [("ok",)]:
            raise ValueError("GeoPackage com erro de integridade.")
        tables = connection.execute(
            """SELECT c.table_name FROM gpkg_contents c
            JOIN gpkg_geometry_columns g ON g.table_name=c.table_name
            JOIN gpkg_spatial_ref_sys s ON s.srs_id=g.srs_id
            WHERE c.data_type='features' AND g.srs_id NOT IN (-1,0)"""
        ).fetchall()
        if len(tables) != 1:
            raise ValueError(
                "Esperada uma camada vetorial explícita, com sistema de coordenadas definido."
            )
        table = '"' + tables[0][0].replace('"', '""') + '"'
        if connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is None:
            raise ValueError("Camada vetorial vazia.")
        if uf:
            if uf not in UFS:
                raise ValueError("UF desconhecida.")
            fields = {
                row[1].lower(): row[1]
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            field = next(
                (
                    fields[name]
                    for name in (
                        "cod_imovel",
                        "codigo_imovel",
                        "num_car",
                        "numero_car",
                        "car",
                        "cod_car",
                    )
                    if name in fields
                ),
                None,
            )
            if field is None:
                raise ValueError("Identificador CAR ausente na base estadual.")
            quoted = '"' + field.replace('"', '""') + '"'
            mismatch = connection.execute(
                f"SELECT 1 FROM {table} WHERE {quoted} IS NULL OR upper(substr({quoted},1,2)) <> ? LIMIT 1",
                (uf,),
            ).fetchone()
            if mismatch:
                raise ValueError(
                    "A base contém CAR sem identificação ou de UF diferente da esperada."
                )
        return True
    finally:
        connection.close()


def reconcile_features(
    ids: Sequence[object],
    features: Iterable[Mapping[str, Any]],
    id_field: str,
) -> list[Mapping[str, Any]]:
    found: list[str] = []
    collected: list[Mapping[str, Any]] = []
    for feature in features:
        value = feature.get("id")
        if value is None:
            value = (feature.get("properties") or {}).get(id_field)
        if value is None:
            raise ValueError(
                "Resposta sem identificador de feição; completude não comprovada."
            )
        found.append(str(value))
        collected.append(feature)
    if len(found) != len(set(found)) or set(found) != {str(value) for value in ids}:
        raise ValueError(
            "Download incompleto ou duplicado: os IDs recebidos diferem dos solicitados."
        )
    return collected
