from __future__ import annotations

import json
import zipfile
from pathlib import Path

from installer.update_package import build_update_package


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
        assert manifest["id"] == "mte"
        assert archive.testzip() is None


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
