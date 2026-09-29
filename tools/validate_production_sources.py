"""Valida estruturalmente as fontes reais antes de montar pacotes de produção."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from database.schema import initialize
from database.session import connect
from qgis_plugin_microcredito.application.import_service import (
    ALIASES_BY_TYPE,
    _validate_headers,
)
from qgis_plugin_microcredito.application.mte_service import import_mte
from qgis_plugin_microcredito.infrastructure.csv_reader import iter_rows
from qgis_plugin_microcredito.infrastructure.downloads import (
    validate_geopackage,
    validate_zip,
)

try:
    from tools.inventory_production_sources import ENVIRONMENTAL, SICOR, UFS, inventory
except (
    ModuleNotFoundError
):  # execução direta: python scripts/validate_production_sources.py
    from inventory_production_sources import ENVIRONMENTAL, SICOR, UFS, inventory


REQUIRED_SICOR = {
    "mutuarios": ("ref_bacen", "documento"),
    "propriedades": ("ref_bacen", "car"),
    "operacoes": ("ref_bacen", "nu_ordem"),
    "complementos": ("ref_bacen", "nu_ordem"),
    "glebas": ("ref_bacen", "nu_ordem"),
}


def _quick_check(path: Path) -> None:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("Banco SQLite não passou no PRAGMA quick_check.")
    finally:
        connection.close()


def _sicar_mismatch_summary(path: Path, expected_uf: str) -> dict[str, object]:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        table = connection.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
        ).fetchone()[0]
        quoted_table = '"' + str(table).replace('"', '""') + '"'
        fields = {
            str(row[1]).lower(): str(row[1])
            for row in connection.execute(f"PRAGMA table_info({quoted_table})")
        }
        field = next(
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
        )
        quoted_field = '"' + field.replace('"', '""') + '"'
        condition = f"{quoted_field} IS NULL OR upper(substr({quoted_field},1,2)) <> ?"
        invalid = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {quoted_table} WHERE {condition}", (expected_uf,)
            ).fetchone()[0]
        )
        total = int(
            connection.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()[0]
        )
        prefixes = {
            str(row[0] or "NULO"): int(row[1])
            for row in connection.execute(
                f"SELECT upper(substr({quoted_field},1,2)), COUNT(*) FROM {quoted_table} "
                f"WHERE {condition} GROUP BY upper(substr({quoted_field},1,2)) ORDER BY COUNT(*) DESC",
                (expected_uf,),
            )
        }
        return {"total": total, "invalidos": invalid, "prefixos_invalidos": prefixes}
    finally:
        connection.close()


def validate(
    data_root: Path, database: Path, mte_source: Path | None = None
) -> dict[str, object]:
    root = data_root.resolve()
    report = inventory(root, mte_source)
    checked: list[dict[str, object]] = []

    for uf in UFS:
        relative = f"car/{uf}/{uf}_AREA_IMOVEL.gpkg"
        print(f"Validando SICAR/{uf}…", flush=True)
        try:
            diagnostic = _sicar_mismatch_summary(root / relative, uf)
            foreign_count = int(diagnostic["invalidos"])
            if foreign_count > 1000:
                raise ValueError(
                    "Exceções de UF acima do limite operacional de 1000 registros."
                )
            validate_geopackage(
                root / relative, uf=uf, expected_foreign_features=foreign_count
            )
            status = "valida_com_excecao_de_origem" if foreign_count else "valida"
            checked.append(
                {
                    "base": f"sicar_imoveis_{uf.lower()}",
                    "path": relative,
                    "status": status,
                    "foreign_feature_count": foreign_count,
                    "diagnostico": diagnostic,
                }
            )
        except Exception as exc:
            checked.append(
                {
                    "base": f"sicar_imoveis_{uf.lower()}",
                    "path": relative,
                    "status": "bloqueada",
                    "erro": str(exc),
                    "diagnostico": _sicar_mismatch_summary(root / relative, uf),
                }
            )

    for identifier, relative in ENVIRONMENTAL.items():
        print(f"Validando {identifier}…", flush=True)
        try:
            validate_geopackage(root / relative)
            checked.append({"base": identifier, "path": relative, "status": "valida"})
        except Exception as exc:
            checked.append(
                {
                    "base": identifier,
                    "path": relative,
                    "status": "bloqueada",
                    "erro": str(exc),
                }
            )

    for payload, relative in SICOR.items():
        kind = "glebas" if payload.startswith("glebas") else payload
        print(f"Validando cabeçalho Sicor/{payload}…", flush=True)
        if not (root / relative).is_file():
            checked.append(
                {
                    "base": "sicor",
                    "payload": payload,
                    "path": relative,
                    "status": "ausente",
                }
            )
            continue
        try:
            rows = iter_rows(root / relative)
            first = next(rows)
            _validate_headers(first, ALIASES_BY_TYPE[kind], REQUIRED_SICOR[kind])
            checked.append(
                {
                    "base": "sicor",
                    "payload": payload,
                    "path": relative,
                    "status": "valida",
                }
            )
        except Exception as exc:
            checked.append(
                {
                    "base": "sicor",
                    "payload": payload,
                    "path": relative,
                    "status": "bloqueada",
                    "erro": str(exc),
                }
            )

    mma_candidates = sorted((root / "mma").glob("*.zip"))
    mma = mma_candidates[-1]
    print("Validando ZIP MMA/MCR…", flush=True)
    try:
        validate_zip(mma)
        checked.append(
            {
                "base": "mma_mcr",
                "path": mma.relative_to(root).as_posix(),
                "status": "valida",
            }
        )
    except Exception as exc:
        checked.append(
            {
                "base": "mma_mcr",
                "path": mma.relative_to(root).as_posix(),
                "status": "bloqueada",
                "erro": str(exc),
            }
        )

    mte = (
        mte_source.resolve()
        if mte_source
        else root / "normativos" / "cadastro_empregadores_trabalho_escravo.csv"
    )
    print("Validando publicação MTE em banco temporário…", flush=True)
    try:
        temporary = sqlite3.connect(":memory:")
        temporary.row_factory = sqlite3.Row
        try:
            initialize(temporary)
            total_mte = import_mte(
                temporary,
                mte,
                validade_ate="2099-12-31",
                source_reference="validacao-local",
            )
        finally:
            temporary.close()
        checked.append(
            {
                "base": "mte",
                "path_included": False,
                "status": "valida",
                "registros": total_mte,
            }
        )
    except Exception as exc:
        checked.append(
            {
                "base": "mte",
                "path_included": False,
                "status": "bloqueada",
                "erro": str(exc),
            }
        )

    print("Executando integridade do banco SQLite ativo…", flush=True)
    try:
        _quick_check(database.resolve())
        readonly = connect(database.resolve(), readonly=True)
        try:
            active_imports = readonly.execute(
                "SELECT tipo, COUNT(*) quantidade FROM importacao WHERE ativo=1 GROUP BY tipo ORDER BY tipo"
            ).fetchall()
            database_summary = {
                str(row["tipo"]): int(row["quantidade"]) for row in active_imports
            }
        finally:
            readonly.close()
        checked.append(
            {
                "base": "banco_local",
                "path_included": False,
                "status": "valida",
                "importacoes_ativas": database_summary,
            }
        )
    except Exception as exc:
        checked.append(
            {
                "base": "banco_local",
                "path_included": False,
                "status": "bloqueada",
                "erro": str(exc),
            }
        )

    structurally_approved = all(
        item["status"] in ("valida", "valida_com_excecao_de_origem") for item in checked
    )
    available_sources_approved = all(
        item["status"] in ("valida", "valida_com_excecao_de_origem", "ausente")
        for item in checked
    )
    return {
        "schema_version": 1,
        "validated_at": datetime.now().astimezone().isoformat(),
        # `approved` permanece por compatibilidade com o código de saída. Ele
        # representa somente a aprovação estrutural, nunca autoriza publicação.
        "approved": structurally_approved,
        "structurally_approved": structurally_approved,
        "available_sources_approved": available_sources_approved,
        "ready_for_publication": False,
        "technical_inventory_ready": report["technically_ready"],
        "publication_blockers": report["publication_blockers"],
        "logical_bases": report["logical_bases"],
        "planned_packages": report["planned_packages"],
        "checks": checked,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--mte-source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = validate(arguments.data_root, arguments.database, arguments.mte_source)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "structurally_approved": result["structurally_approved"],
                "available_sources_approved": result["available_sources_approved"],
                "ready_for_publication": result["ready_for_publication"],
                "checks": len(result["checks"]),
            },
            indent=2,
        ),
        flush=True,
    )
    raise SystemExit(0 if result["approved"] else 1)
