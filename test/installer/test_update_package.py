from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from installer.base_release import build_base_release
from installer.update_package import build_update_package
from qgis_plugin_microcredito.infrastructure.updates import (
    TEST_PUBLISHER_PUBLIC_KEY_PEM,
)


def test_build_update_package_records_payload_and_hash(tmp_path: Path) -> None:
    payload = tmp_path / "mte.csv"
    payload.write_text("ID;CNPJ_CPF\n1;12345678901\n", encoding="utf-8")
    destination = tmp_path / "mte.zip"

    result = build_update_package(
        "mte",
        "2026.09.23",
        "import_mte",
        {"file": payload},
        destination,
    )

    assert result["size_bytes"] == destination.stat().st_size
    assert len(str(result["sha256"])) == 64
    with zipfile.ZipFile(destination) as archive:
        manifest = json.loads(archive.read("package.json"))
        assert manifest["schema_version"] == 1
        assert manifest["id"] == "mte"
        assert archive.testzip() is None


def test_build_base_release_contains_only_signed_catalog_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "mte.zip"
    package.write_bytes(b"pacote-validado")
    import hashlib

    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "issued_at": "2026-10-15T12:00:00-03:00",
                "expires_at": "2027-10-15T12:00:00-03:00",
                "packages": [
                    {
                        "id": "mte",
                        "label": "Cadastro MTE",
                        "version": "2026.10.06",
                        "strategy": "import_mte",
                        "url": "carbases://packages/mte.zip",
                        "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
                        "size_bytes": package.stat().st_size,
                        "validity_until": "2027-04-05",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    signature = tmp_path / "catalog.json.sig"
    signature.write_bytes(b"assinatura")
    monkeypatch.setattr(
        "installer.base_release.verify_catalog_signature",
        lambda *_args: None,
    )

    destination = tmp_path / "bases-2026-10.carbases"
    result = build_base_release(
        catalog,
        signature,
        {"mte": package},
        destination,
        TEST_PUBLISHER_PUBLIC_KEY_PEM,
    )

    assert result["packages"] == 1
    assert result["size_bytes"] == destination.stat().st_size
    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == {
            "catalog.json",
            "catalog.json.sig",
            "packages/mte.zip",
        }


def test_build_base_release_rejects_package_not_declared_by_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "issued_at": "2026-10-15T12:00:00-03:00",
                "expires_at": "2027-10-15T12:00:00-03:00",
                "packages": [
                    {
                        "id": "mte",
                        "label": "Cadastro MTE",
                        "version": "2026.10.06",
                        "strategy": "import_mte",
                        "url": "https://publisher.example/mte.zip",
                        "sha256": "a" * 64,
                        "size_bytes": 123,
                        "validity_until": "2027-04-05",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    signature = tmp_path / "catalog.json.sig"
    signature.write_bytes(b"assinatura")
    unexpected = tmp_path / "inesperado.zip"
    unexpected.write_bytes(b"x")
    monkeypatch.setattr(
        "installer.base_release.verify_catalog_signature",
        lambda *_args: None,
    )

    with pytest.raises(ValueError, match="exatamente os pacotes"):
        build_base_release(
            catalog,
            signature,
            {"inesperado": unexpected},
            tmp_path / "release.carbases",
            TEST_PUBLISHER_PUBLIC_KEY_PEM,
        )


def test_replace_file_rejects_path_traversal(tmp_path: Path) -> None:
    payload = tmp_path / "base.gpkg"
    payload.write_bytes(b"fixture")
    try:
        build_update_package(
            "embargos",
            "2026.09.23",
            "replace_file",
            {"file": payload},
            tmp_path / "base.zip",
            target="../fora.gpkg",
        )
    except ValueError as exc:
        assert "fora da pasta" in str(exc)
    else:
        raise AssertionError("O caminho inseguro deveria ser rejeitado.")


def test_sicor_package_rejects_duplicate_geometry_scopes(tmp_path: Path) -> None:
    payloads = {}
    for name in ("mutuarios", "propriedades", "glebas_2025", "glebas_2026"):
        path = tmp_path / f"{name}.csv"
        path.write_text("fixture", encoding="utf-8")
        payloads[name] = path

    destination = tmp_path / "sicor.zip"
    with pytest.raises(
        ValueError,
        match="Arquivos de geometria Sicor exigem escopos distintos",
    ):
        build_update_package(
            "sicor_operacoes_car",
            "2026.09.29",
            "import_sicor",
            payloads,
            destination,
            payload_scopes={
                "glebas_2025": "2025-nacional",
                "glebas_2026": "2025-nacional",
            },
        )

    assert not destination.exists()
