from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from installer.constants import ENVIRONMENTAL, PLUGIN_VERSION, UFS, repository_root
from installer.install import install_package
from installer.plugin_build import plugin_files
from installer.verify import verify_package


def test_repository_root_contains_plugin_sources() -> None:
    root = repository_root()
    assert (root / "src" / "plugin" / "metadata.txt").is_file()
    assert (root / "src" / "qgis_plugin_microcredito").is_dir()
    assert (root / "src" / "database").is_dir()


def test_plugin_files_include_metadata_and_bundled_lib() -> None:
    files = plugin_files()
    assert "metadata.txt" in files
    assert any(name.startswith("lib/qgis_plugin_microcredito/") for name in files)
    assert any(name.startswith("lib/database/") for name in files)
    assert "supreme_mode.txt" not in files
    supreme = plugin_files(supreme=True)
    assert supreme["supreme_mode.txt"] == b"enabled\n"


def _write_package(root: Path, variant: str = "individual") -> Path:
    package = root / "package"
    folder = (
        "car_microcredito_supremo_qgis"
        if variant == "massa"
        else "car_microcredito_qgis"
    )
    plugin_dir = package / "arquivos" / "plugin" / folder
    plugin_dir.mkdir(parents=True)
    files = plugin_files(supreme=variant == "massa")
    for relative, content in files.items():
        destination = plugin_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    car_root = package / "arquivos" / "dados" / "car"
    for uf in UFS:
        folder_uf = car_root / uf
        folder_uf.mkdir(parents=True)
        (folder_uf / f"{uf}_AREA_IMOVEL.gpkg").write_bytes(b"fixture")
    ambientais = package / "arquivos" / "dados" / "ambientais"
    ambientais.mkdir(parents=True)
    for name in ENVIRONMENTAL:
        (ambientais / name).write_bytes(b"fixture")
    db = package / "arquivos" / "dados" / "car_microcredito.db"
    sqlite3.connect(db).close()
    manifest = {}
    for path in package.rglob("*"):
        if path.is_file():
            relative = path.relative_to(package).as_posix()
            manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    (package / "MANIFESTO_SHA256.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return package


def test_verify_and_install_both_variants(tmp_path: Path) -> None:
    for variant in ("individual", "massa"):
        package = _write_package(tmp_path / uuid4().hex, variant)
        verify_package(package)
        profiles = tmp_path / f"{variant}_profiles"
        installed = install_package(
            package,
            profiles_root=profiles,
            skip_settings=True,
            skip_qgis_check=True,
        )
        assert installed
        metadata = (installed[0] / "metadata.txt").read_text(encoding="utf-8")
        assert f"version={PLUGIN_VERSION}" in metadata
        assert (installed[0] / "supreme_mode.txt").is_file() == (variant == "massa")
