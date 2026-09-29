"""Audita registros SICAR armazenados no arquivo de UF diferente do CAR.

O relatório contém somente contagens e prefixos; números CAR não são gravados.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

try:
    from tools.inventory_production_sources import UFS
except ModuleNotFoundError:
    from inventory_production_sources import UFS


CAR_FIELDS = ("cod_imovel", "codigo_imovel", "num_car", "numero_car", "car", "cod_car")


def _open(path: Path) -> tuple[sqlite3.Connection, str, str]:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    table = str(
        connection.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
        ).fetchone()[0]
    )
    quoted_table = '"' + table.replace('"', '""') + '"'
    fields = {
        str(row[1]).lower(): str(row[1])
        for row in connection.execute(f"PRAGMA table_info({quoted_table})")
    }
    field = next(fields[name] for name in CAR_FIELDS if name in fields)
    return connection, quoted_table, '"' + field.replace('"', '""') + '"'


def audit(data_root: Path) -> dict[str, object]:
    root = data_root.resolve()
    routed: dict[tuple[str, str], list[str]] = {}
    for source_uf in UFS:
        path = root / "car" / source_uf / f"{source_uf}_AREA_IMOVEL.gpkg"
        connection, table, field = _open(path)
        try:
            rows = connection.execute(
                f"SELECT {field} FROM {table} WHERE {field} IS NULL OR upper(substr({field},1,2)) <> ?",
                (source_uf,),
            )
            for row in rows:
                value = str(row[0] or "")
                target_uf = value[:2].upper() if len(value) >= 2 else "NULO"
                routed.setdefault((source_uf, target_uf), []).append(value)
        finally:
            connection.close()

    summary = []
    for (source_uf, target_uf), identifiers in sorted(routed.items()):
        found = 0
        if target_uf in UFS:
            target_path = root / "car" / target_uf / f"{target_uf}_AREA_IMOVEL.gpkg"
            connection, table, field = _open(target_path)
            try:
                for start in range(0, len(identifiers), 500):
                    values = identifiers[start : start + 500]
                    marks = ",".join("?" for _ in values)
                    found += int(
                        connection.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE {field} IN ({marks})",
                            values,
                        ).fetchone()[0]
                    )
            finally:
                connection.close()
        summary.append(
            {
                "arquivo_origem": source_uf,
                "prefixo_car": target_uf,
                "registros_fora_da_uf": len(identifiers),
                "tambem_presentes_no_arquivo_correto": found,
                "ausentes_no_arquivo_correto": len(identifiers) - found,
            }
        )
    return {
        "schema_version": 1,
        "contains_car_identifiers": False,
        "total_fora_da_uf": sum(len(values) for values in routed.values()),
        "rotas": summary,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = audit(arguments.data_root)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
