from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from pytest import MonkeyPatch
from tools import validate_production_sources
from tools.audit_base_release_packages import _audit_package
from tools.audit_base_release_packages import audit as audit_base_release
from tools.audit_sicar_state_routing import audit
from tools.inventory_production_sources import UFS, inventory
from tools.publisher_cycle import load_source_config, start_cycle, validate_cycle
from tools.upgrade_update_packages import upgrade_package

from installer.update_package import build_update_package
from qgis_plugin_microcredito.domain.base_catalog import BASE_DEFINITIONS


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


def test_signed_catalog_requires_powershell_75_for_date_kind() -> None:
    script = (
        Path(__file__).parents[1] / "tools" / "build_signed_catalog.ps1"
    ).read_text(encoding="utf-8")

    assert 'if ($PSVersionTable.PSVersion -lt [version]"7.5") {' in script
    assert "A assinatura exige PowerShell 7.5+" in script
    assert "ConvertFrom-Json -DateKind String" in script


@pytest.mark.parametrize("suffix", [".zip", ".txt"])
def test_release_audit_rejects_nested_mma_payload(tmp_path: Path, suffix: str) -> None:
    source = tmp_path / f"mma{suffix}"
    source.write_bytes(b"conteudo-incompativel")
    package = tmp_path / "mma_mcr.zip"
    build_update_package(
        "mma_mcr",
        "2026.10.15",
        "import_mma_mcr",
        {"file": source},
        package,
    )

    with pytest.raises(ValueError, match="Formato de payload incompatível"):
        _audit_package(package)


def test_release_audit_accepts_csv_mma_payload(tmp_path: Path) -> None:
    source = tmp_path / "mma.csv"
    source.write_text("CAR;STATUS\nPA-TESTE;ATIVO\n", encoding="utf-8")
    package = tmp_path / "mma_mcr.zip"
    build_update_package(
        "mma_mcr",
        "2026.10.15",
        "import_mma_mcr",
        {"file": source},
        package,
    )

    report = _audit_package(package)

    assert report["id"] == "mma_mcr"
    assert report["strategy"] == "import_mma_mcr"


def test_catalog_template_declares_evidence_and_runtime_compatibility() -> None:
    root = Path(__file__).parents[1]
    template = json.loads(
        (root / "updates" / "producao" / "catalog.template.example.json").read_text(
            encoding="utf-8"
        )
    )
    script = (root / "tools" / "build_signed_catalog.ps1").read_text(encoding="utf-8")

    assert template["schema_version"] == 3
    package = template["packages"][0]
    assert set(package["source_evidence"]) == {
        "official_page_url",
        "official_artifact_url",
        "checked_at",
    }
    assert set(package["compatibility"]) == {
        "minimum_plugin_version",
        "maximum_plugin_version",
        "database_schema_version",
        "package_manifest_schema_version",
    }
    assert "source_evidence" in script
    assert "compatibility" in script
    assert "schema_version = 3" in script


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


@pytest.mark.parametrize(
    "checked_at",
    ("2026-10-15T09:00:00-03:00", "2026-10-15T12:00:00+00:00"),
)
def test_publisher_cycle_covers_all_sources_and_repeats_after_fourteen_days(
    tmp_path: Path, checked_at: str
) -> None:
    root = Path(__file__).parents[1]
    config_path = root / "updates" / "publisher" / "sources.json"
    config = load_source_config(config_path)
    destination = tmp_path / "revisao-quinzenal.json"

    report = start_cycle(
        config_path,
        destination,
        datetime.fromisoformat(checked_at),
    )

    assert config["cadence_days"] == 14
    assert len(report["sources"]) == 11
    assert datetime.fromisoformat(str(report["next_due_at"])) == datetime.fromisoformat(
        "2026-10-29T09:00:00-03:00"
    )
    assert {source["result"] for source in report["sources"]} == {"pendente"}
    assert destination.with_suffix(".html").is_file()
    with pytest.raises(ValueError, match="ainda pendente"):
        validate_cycle(report, require_complete=True)


def test_inventory_redacts_explicit_mte_source_path(tmp_path: Path) -> None:
    mte_source = tmp_path / "usuario-operador" / "restrito" / "cadastro-mte.csv"

    report = inventory(tmp_path / "dados", mte_source)

    mte_package = next(
        package for package in report["packages"] if package["id"] == "mte"
    )
    assert mte_package["sources"] == [
        {
            "path": "cadastro-mte.csv",
            "path_included": False,
            "present": False,
            "size_bytes": None,
            "fits_github_release": False,
        }
    ]
    assert "cadastro-mte.csv" in report["missing_sources"]
    assert str(mte_source.parent) not in json.dumps(report, ensure_ascii=False)


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


def test_sicar_routing_audit_counts_distinct_car_identifiers(tmp_path: Path) -> None:
    for uf in UFS:
        identifiers = [f"{uf}-REGISTRO"]
        if uf == "AC":
            identifiers.extend(["AL-DUPLICADO", "AL-DUPLICADO"])
        if uf == "AL":
            identifiers.extend(["AL-DUPLICADO", "AL-DUPLICADO"])
        _create_sicar_source(
            tmp_path / "car" / uf / f"{uf}_AREA_IMOVEL.gpkg",
            identifiers,
        )

    report = audit(tmp_path)

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


@pytest.mark.parametrize(
    "payload_name",
    ["../escaped", "absolute", "nested/escaped", "..\\escaped", "x" * 101],
)
def test_upgrade_rejects_unsafe_payload_names_before_extracting(
    tmp_path: Path, payload_name: str
) -> None:
    source = tmp_path / "legacy.zip"
    destination = tmp_path / "rebuilt.zip"
    destination.write_bytes(b"existing publication")
    work = tmp_path / "work"
    work.mkdir()
    if payload_name == "absolute":
        payload_name = str(tmp_path / "escaped")
    manifest = {
        "schema_version": 0,
        "id": "mma_mcr",
        "version": "2026.10.15",
        "strategy": "import_mma_mcr",
        "provides": ["mma_mcr"],
        "payloads": {payload_name: "payload/source.csv"},
    }
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("package.json", json.dumps(manifest))
        archive.writestr("payload/source.csv", b"SYNTHETIC\n")
    original_source = source.read_bytes()

    with pytest.raises(ValueError, match="Nome de payload"):
        upgrade_package(source, destination, work)

    assert source.read_bytes() == original_source
    assert destination.read_bytes() == b"existing publication"
    assert {path for path in tmp_path.rglob("*") if path.is_file()} == {
        source,
        destination,
    }


def test_upgrade_preserves_valid_payload_and_source(tmp_path: Path) -> None:
    payload = tmp_path / "source.csv"
    payload.write_bytes(b"SYNTHETIC;CONTENT\n")
    source = tmp_path / "source.zip"
    build_update_package(
        "mma_mcr", "2026.10.15", "import_mma_mcr", {"file": payload}, source
    )
    original_source = source.read_bytes()
    destination = tmp_path / "rebuilt.zip"
    work = tmp_path / "work"
    work.mkdir()

    report = upgrade_package(source, destination, work)

    assert report["status"] == "rebuilt"
    assert source.read_bytes() == original_source
    assert not list(work.iterdir())
    with zipfile.ZipFile(destination) as archive:
        manifest = json.loads(archive.read("package.json"))
        assert set(manifest["payloads"]) == {"file"}
        assert archive.read(manifest["payloads"]["file"]) == b"SYNTHETIC;CONTENT\n"


def _publication_for_sicor_audit(
    root: Path, sicor_payload_names: tuple[str, ...]
) -> Path:
    packages = root / "packages"
    packages.mkdir()
    tabular = root / "source.csv"
    tabular.write_bytes(b"SYNTHETIC\n")
    spatial = root / "source.gpkg"
    spatial.write_bytes(b"synthetic payload for structural audit only")
    for definition in BASE_DEFINITIONS:
        if definition.relative_path is not None:
            build_update_package(
                definition.identifier,
                "2026.10.15",
                "replace_file",
                {"file": spatial},
                packages / f"{definition.identifier}.zip",
                target=definition.relative_path,
            )
    for uf in UFS:
        build_update_package(
            f"sicar_imoveis_{uf.lower()}",
            "2026.10.15",
            "replace_file",
            {"file": spatial},
            packages / f"sicar_imoveis_{uf.lower()}.zip",
            target=f"car/{uf}/{uf}_AREA_IMOVEL.gpkg",
        )
    for identifier, strategy in (("mma_mcr", "import_mma_mcr"), ("mte", "import_mte")):
        build_update_package(
            identifier,
            "2026.10.15",
            strategy,
            {"file": tabular},
            packages / f"{identifier}.zip",
        )
    manifest = {
        "schema_version": 1,
        "id": "sicor_operacoes_car",
        "version": "2026.10.15",
        "strategy": "import_sicor",
        "provides": ["sicor_operacoes_car", "sicor_geometrias"],
        "payloads": {name: f"payload/{name}.csv" for name in sicor_payload_names},
        "payload_scopes": {
            name: f"sicor:{name}"
            for name in sicor_payload_names
            if name.startswith("glebas")
        },
    }
    with zipfile.ZipFile(packages / "sicor_operacoes_car.zip", "w") as archive:
        archive.writestr("package.json", json.dumps(manifest))
        for name in sicor_payload_names:
            archive.writestr(f"payload/{name}.csv", b"SYNTHETIC\n")
    return packages


@pytest.mark.parametrize(
    "sicor_payload_names",
    [
        ("mutuarios", "propriedades"),
        ("mutuarios", "propriedades", "glebas"),
        ("mutuarios", "propriedades", "complementos", "glebas"),
        ("mutuarios", "propriedades", "operacoes", "glebas"),
        ("mutuarios", "propriedades", "operacoes", "complementos"),
        ("propriedades", "operacoes", "complementos", "glebas"),
        ("mutuarios", "operacoes", "complementos", "glebas"),
    ],
)
def test_publication_audit_rejects_sicor_with_missing_components(
    tmp_path: Path, sicor_payload_names: tuple[str, ...]
) -> None:
    packages = _publication_for_sicor_audit(tmp_path, sicor_payload_names)

    with pytest.raises(ValueError, match="Sicor"):
        audit_base_release(packages)


@pytest.mark.parametrize("geometry", [("glebas",), ("glebas_ac", "glebas_pa")])
def test_publication_audit_accepts_complete_sicor_including_multiple_scopes(
    tmp_path: Path, geometry: tuple[str, ...]
) -> None:
    packages = _publication_for_sicor_audit(
        tmp_path, ("mutuarios", "propriedades", "operacoes", "complementos", *geometry)
    )

    report = audit_base_release(packages)

    assert report["approved"] is True
    assert report["technical_packages"] == 36
    assert report["logical_bases"] == 11
    sicor = next(
        package
        for package in report["packages"]
        if package["id"] == "sicor_operacoes_car"
    )
    assert sicor["provides"] == ["sicor_operacoes_car", "sicor_geometrias"]
