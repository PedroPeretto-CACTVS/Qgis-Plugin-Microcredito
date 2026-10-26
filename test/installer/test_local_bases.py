import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from database.schema import initialize
from database.session import connect
from installer.constants import ENVIRONMENTAL, UFS
from installer.local_bases import install_local_bases
from qgis_plugin_microcredito.application.backup_service import snapshot_database
from qgis_plugin_microcredito.application.local_data_paths import (
    default_local_data_paths,
)
from qgis_plugin_microcredito.application.query_service import find_fiscal_module
from qgis_plugin_microcredito.infrastructure.updates import (
    ensure_not_updating,
    latest_restore_point,
    restore_latest,
)


def dataset(root: Path) -> Path:
    database = root / "homologacao-R2.db"
    connection = connect(database)
    initialize(connection)
    connection.close()
    for relative in (
        *(f"car/{uf}/{uf}_AREA_IMOVEL.gpkg" for uf in UFS),
        *(f"ambientais/{name}" for name in ENVIRONMENTAL),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as gpkg:
            gpkg.executescript("""
                CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT);
                CREATE TABLE gpkg_geometry_columns (table_name TEXT, srs_id INTEGER);
                CREATE TABLE gpkg_spatial_ref_sys (srs_id INTEGER);
                CREATE TABLE area (id INTEGER);
                INSERT INTO gpkg_contents VALUES ('area', 'features');
                INSERT INTO gpkg_geometry_columns VALUES ('area', 4674);
                INSERT INTO gpkg_spatial_ref_sys VALUES (4674);
                INSERT INTO area VALUES (1);
            """)
    return database


def test_migration_copies_one_coherent_set_and_survives_source_relocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    source = dataset(tmp_path / "kit-R2")
    source_bytes = source.read_bytes()
    installed = install_local_bases(source)
    source.parent.rename(tmp_path / "kit-arquivado")
    assert installed.root == tmp_path / "local" / "Cactvs" / "BasesPlugin"
    assert installed.database.name == "car_microcredito.db"
    with closing(connect(installed.database, readonly=True)) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM incra_modulo_fiscal").fetchone()[0]
            == 5571
        )
    assert len(list(installed.car.rglob("*.gpkg"))) == 27
    assert len(list(installed.environmental.glob("*.gpkg"))) == 6
    assert (tmp_path / "kit-arquivado" / source.name).read_bytes() == source_bytes


def test_new_plugin_install_preserves_existing_fixed_bases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    source = dataset(tmp_path / "kit-R2")
    installed = install_local_bases(source)
    saved = {
        p.relative_to(installed.root): p.read_bytes()
        for p in installed.root.rglob("*")
        if p.is_file()
    }
    source.write_bytes(b"old or broken distribution")
    repeated = install_local_bases(source)
    assert repeated == installed
    assert saved == {
        p.relative_to(installed.root): p.read_bytes()
        for p in installed.root.rglob("*")
        if p.is_file()
    }


def test_failed_migration_does_not_activate_partial_bases_or_change_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    source = dataset(tmp_path / "kit-R2")
    broken = source.parent / "ambientais" / "embargos.gpkg"
    broken.write_bytes(b"invalid geopackage")
    before = {
        p.relative_to(source.parent): p.read_bytes()
        for p in source.parent.rglob("*")
        if p.is_file()
    }
    with pytest.raises(sqlite3.DatabaseError):
        install_local_bases(source)
    assert not default_local_data_paths().root.exists()
    # Readonly SQLite may create transient WAL/SHM coordination files.
    assert before == {
        relative: (source.parent / relative).read_bytes() for relative in before
    }


def test_partial_existing_destination_is_preserved_on_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    source = dataset(tmp_path / "kit-R2")
    root = default_local_data_paths().root
    root.mkdir(parents=True)
    pending = root / "pending.txt"
    pending.write_text("previous interrupted installation")
    with pytest.raises(ValueError, match="instalação incompleta"):
        install_local_bases(source)
    assert pending.read_text() == "previous interrupted installation"
    assert not (root / "car_microcredito.db").exists()


def test_migration_keeps_legacy_restore_available_when_database_name_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    source = dataset(tmp_path / "kit-R2")
    with closing(connect(source)) as connection:
        connection.execute(
            "INSERT INTO incra_modulo_fiscal VALUES (?, ?, ?, ?, ?)",
            ("0000001", 10, "fixture", "https://example.test", "2026-01-01"),
        )
        connection.commit()
    # A 0.9.0 snapshot has no restore.json and retains the source database name.
    key = hashlib.sha256(b"mte").hexdigest()[:16]
    snapshot_database(
        source, source.parent / ".h" / key / "2601010000000000" / source.name
    )
    with closing(connect(source)) as connection:
        connection.execute(
            "UPDATE incra_modulo_fiscal SET modulo_fiscal_ha = 20 "
            "WHERE codigo_municipio = '0000001'"
        )
        connection.commit()
    original_point = latest_restore_point(source.parent, source)
    assert original_point is not None and original_point.legacy

    installed = install_local_bases(source)

    migrated_point = latest_restore_point(installed.root, installed.database)
    assert migrated_point is not None
    assert migrated_point.restore_id == original_point.restore_id
    restore_latest(installed.root, installed.database)
    with closing(connect(installed.database, readonly=True)) as connection:
        assert find_fiscal_module(connection, "0000001")["modulo_fiscal_ha"] == 10
    with closing(connect(source, readonly=True)) as connection:
        assert find_fiscal_module(connection, "0000001")["modulo_fiscal_ha"] == 20


def test_migration_accepts_inactive_lock_scaffolding_without_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    source = dataset(tmp_path / "kit-R2")
    paths = default_local_data_paths()
    ensure_not_updating(paths.root)
    assert not paths.database.exists()

    installed = install_local_bases(source)

    assert installed.database.is_file()
    assert len(list(installed.car.rglob("*.gpkg"))) == 27
    assert source.is_file()
