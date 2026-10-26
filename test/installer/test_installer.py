from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from pytest import MonkeyPatch
from typer.testing import CliRunner

from database.schema import initialize
from installer.cli import app
from installer.constants import ENVIRONMENTAL, PLUGIN_VERSION, UFS, repository_root
from installer.install import install_package
from installer.plugin_build import plugin_files
from installer.verify import verify_package
from qgis_plugin_microcredito.application.local_data_paths import (
    default_local_data_paths,
)
from qgis_plugin_microcredito.infrastructure.downloads import validate_geopackage


@pytest.fixture(autouse=True)
def isolated_installation_environment(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming-app-data"))
    if sys.platform == "win32":

        def reject_registry_write(*args: object, **kwargs: object) -> None:
            raise AssertionError("O instalador não deve gravar caminhos no registro.")

        monkeypatch.setattr("winreg.CreateKey", reject_registry_write)


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


def _write_geopackage(path: Path, identifier: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE gpkg_contents(table_name TEXT, data_type TEXT);
            CREATE TABLE gpkg_geometry_columns(table_name TEXT, srs_id INTEGER);
            CREATE TABLE gpkg_spatial_ref_sys(srs_id INTEGER);
            CREATE TABLE AREA_IMOVEL(cod_imovel TEXT, geom BLOB);
            INSERT INTO gpkg_contents VALUES('AREA_IMOVEL', 'features');
            INSERT INTO gpkg_geometry_columns VALUES('AREA_IMOVEL', 4674);
            INSERT INTO gpkg_spatial_ref_sys VALUES(4674);
        """)
        connection.execute("INSERT INTO AREA_IMOVEL VALUES(?, x'00')", (identifier,))
    connection.close()


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
        _write_geopackage(folder_uf / f"{uf}_AREA_IMOVEL.gpkg", f"{uf}-test")
    ambientais = package / "arquivos" / "dados" / "ambientais"
    ambientais.mkdir(parents=True)
    for name in ENVIRONMENTAL:
        _write_geopackage(ambientais / name, "environmental-test")
    db = package / "arquivos" / "dados" / "car_microcredito.db"
    connection = sqlite3.connect(db)
    try:
        initialize(connection)
        connection.commit()
    finally:
        connection.close()
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
        package = _write_package(tmp_path / variant[0], variant)
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


def test_installed_bases_remain_accessible_after_package_moves(
    tmp_path: Path,
) -> None:
    package = _write_package(tmp_path)
    installed = install_package(
        package,
        profiles_root=tmp_path / "profiles",
        skip_qgis_check=True,
    )
    package.rename(tmp_path / "package-moved")

    paths = default_local_data_paths()
    assert installed[0].is_dir()
    assert paths.database.is_file()
    for uf in UFS:
        assert validate_geopackage(paths.car / uf / f"{uf}_AREA_IMOVEL.gpkg", uf)
    for name in ENVIRONMENTAL:
        assert validate_geopackage(paths.environmental / name)


def test_reinstalling_plugin_preserves_existing_local_bases(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    profiles = tmp_path / "profiles"
    install_package(package, profiles_root=profiles, skip_qgis_check=True)
    paths = default_local_data_paths()
    connection = sqlite3.connect(paths.database)
    try:
        connection.execute("CREATE TABLE installed_base_marker (edition TEXT)")
        connection.execute("INSERT INTO installed_base_marker VALUES ('newer-edition')")
        connection.commit()
    finally:
        connection.close()
    before = {
        path.relative_to(paths.root): path.read_bytes()
        for path in paths.root.rglob("*")
        if path.is_file()
    }

    install_package(package, profiles_root=profiles, skip_qgis_check=True)

    assert before == {
        path.relative_to(paths.root): path.read_bytes()
        for path in paths.root.rglob("*")
        if path.is_file()
    }


def test_migrate_bases_command_reports_fixed_directory_and_progress(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    package = _write_package(tmp_path)
    source = package / "arquivos" / "dados" / "car_microcredito.db"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess("tasklist", 0, stdout=""),
    )

    result = CliRunner().invoke(app, ["migrate-bases", str(source)])

    assert result.exit_code == 0, result.output
    paths = default_local_data_paths()
    assert str(paths.root) in result.output
    assert "Copiando" in result.output
    assert paths.database.is_file()


def test_migration_and_installation_refuse_running_qgis(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            "tasklist", 0, stdout="qgis-ltr-bin.exe"
        ),
    )

    result = CliRunner().invoke(app, ["migrate-bases", str(tmp_path / "source.db")])

    assert result.exit_code == 1
    assert "Feche todas as janelas do QGIS" in result.output
    with pytest.raises(RuntimeError, match="Feche todas as janelas do QGIS"):
        install_package(tmp_path / "package", profiles_root=tmp_path / "profiles")
    assert not default_local_data_paths().root.exists()
    assert not (tmp_path / "profiles").exists()
