from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pytest import MonkeyPatch
from tools import validate_production_sources
from tools.audit_sicar_state_routing import audit
from tools.inventory_production_sources import UFS, inventory


def test_validation_reports_missing_sicar_and_mma_sources(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    data_root = tmp_path / "dados"
    corrupt_sicar = data_root / "car" / "AC" / "AC_AREA_IMOVEL.gpkg"
    corrupt_sicar.parent.mkdir(parents=True)
    corrupt_sicar.write_bytes(b"arquivo-invalido")
    diagnostic_calls: list[tuple[Path, str]] = []

    def reject_corrupt_sicar(path: Path, expected_uf: str) -> dict[str, object]:
        diagnostic_calls.append((path, expected_uf))
        raise ValueError("GeoPackage SICAR inválido")

    monkeypatch.setattr(
        validate_production_sources,
        "_sicar_mismatch_summary",
        reject_corrupt_sicar,
    )

    report = validate_production_sources.validate(
        data_root, tmp_path / "banco-ausente.db"
    )

    sicar_checks = [
        check
        for check in report["checks"]
        if str(check["base"]).startswith("sicar_imoveis_")
    ]
    assert diagnostic_calls == [(corrupt_sicar, "AC")]
    assert len(sicar_checks) == len(UFS)
    assert (
        next(check for check in sicar_checks if check["base"] == "sicar_imoveis_ac")[
            "status"
        ]
        == "bloqueada"
    )
    assert all(
        check["status"] == "ausente"
        for check in sicar_checks
        if check["base"] != "sicar_imoveis_ac"
    )
    assert next(check for check in report["checks"] if check["base"] == "mma_mcr") == {
        "base": "mma_mcr",
        "path": "mma/PUBLICACAO_MMA_A_DEFINIR.zip",
        "status": "ausente",
    }


def _create_sicar_source(path: Path, identifiers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)"
        )
        connection.execute(
            "INSERT INTO gpkg_contents VALUES ('area_imovel', 'features')"
        )
        connection.execute("CREATE TABLE area_imovel (cod_imovel TEXT)")
        connection.executemany(
            "INSERT INTO area_imovel VALUES (?)",
            [(identifier,) for identifier in identifiers],
        )
        connection.commit()
    finally:
        connection.close()


def test_inventory_reports_publication_blockers_without_exposing_root(
    tmp_path: Path,
) -> None:
    report = inventory(tmp_path)

    assert report["schema_version"] == 1
    assert report["logical_bases"] == 11
    assert report["planned_packages"] == 36
    assert report["technically_ready"] is False
    assert report["ready_for_publication"] is False
    assert report["publication_blockers"]
    assert str(tmp_path) not in json.dumps(report, ensure_ascii=False)


def test_sicar_routing_audit_emits_only_aggregates(tmp_path: Path) -> None:
    for uf in UFS:
        identifiers = [f"{uf}-REGISTRO"]
        if uf == "AC":
            identifiers.append("AL-DUPLICADO")
        if uf == "AL":
            identifiers.append("AL-DUPLICADO")
        _create_sicar_source(
            tmp_path / "car" / uf / f"{uf}_AREA_IMOVEL.gpkg",
            identifiers,
        )

    report = audit(tmp_path)

    assert report["contains_car_identifiers"] is False
    assert report["total_fora_da_uf"] == 1
    assert report["rotas"] == [
        {
            "arquivo_origem": "AC",
            "prefixo_car": "AL",
            "registros_fora_da_uf": 1,
            "tambem_presentes_no_arquivo_correto": 1,
            "ausentes_no_arquivo_correto": 0,
        }
    ]
    assert "AL-DUPLICADO" not in json.dumps(report, ensure_ascii=False)
