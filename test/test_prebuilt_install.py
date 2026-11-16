import json
import os
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from update_process_support import TEST_PUBLIC_KEY_PEM


@pytest.fixture(scope="module")
def prebuilt(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from installer.prebuilt_bases import prepare_prebuilt_bases
    from installer.prebuilt_release import build_prebuilt_release
    from prebuilt_support import write_complete_release

    root = tmp_path_factory.mktemp("copy-publicador")
    source = write_complete_release(root / "raw")
    manifest_path = prepare_prebuilt_bases(
        source.release, root / "candidate", TEST_PUBLIC_KEY_PEM
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    from datetime import datetime

    day = datetime.fromisoformat(manifest["prepared_at"]).strftime("%d-%m-%Y")
    release = root / f"bases-plugin-{day}.carbases"
    build_prebuilt_release(root / "candidate", release, TEST_PUBLIC_KEY_PEM)
    return release


def _apply(release: Path, root: Path) -> object:
    from qgis_plugin_microcredito.infrastructure.prebuilt_install import (
        apply_prebuilt_release,
    )
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
    )

    bundle = PrebuiltReleaseBundle(release, TEST_PUBLIC_KEY_PEM)
    pending = root / ".atualizacoes" / "external-update-pending.json"
    pending.parent.mkdir(parents=True, exist_ok=True)
    # Model the public backend precondition with a real marker owned by this
    # fixture. Protocol dispatch and marker cleanup are tested in the next PR.
    with pending.open("x", encoding="utf-8") as stream:
        json.dump({"pid": os.getpid(), "command": "apply"}, stream)
    try:
        return apply_prebuilt_release(bundle, root, root / "car_microcredito.db")
    finally:
        pending.unlink()


def test_snapshot_migration_is_available_even_when_raw_versions_are_current(
    prebuilt: Path, tmp_path: Path
) -> None:
    from qgis_plugin_microcredito.infrastructure.prebuilt_install import (
        compare_prebuilt_release,
    )
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
    )

    release = PrebuiltReleaseBundle(prebuilt, TEST_PUBLIC_KEY_PEM)
    root = tmp_path / "bases"
    release.extract_data(root)

    statuses = compare_prebuilt_release(release, root, root / "car_microcredito.db")

    assert len(statuses) == 36
    assert all(status.state == "disponivel" for status in statuses)


def test_copy_install_preserves_reports_removes_old_history_and_installs_exact_database(
    prebuilt: Path, tmp_path: Path
) -> None:
    from installer.verify import file_sha256
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
    )

    release = PrebuiltReleaseBundle(prebuilt, TEST_PUBLIC_KEY_PEM)
    root = tmp_path / "bases"
    release.extract_data(root)
    report = root / "resultados" / "report.pdf"
    report.parent.mkdir()
    report.write_bytes(b"user report")
    history = root / ".h" / "old"
    history.mkdir(parents=True)
    (history / "history.db").write_bytes(b"old restoration point")

    result = _apply(prebuilt, root)

    assert len(result) == 36
    assert report.read_bytes() == b"user report"
    assert not (root / ".h").exists()
    assert (
        file_sha256(root / "car_microcredito.db")
        == release.manifest["files"]["car_microcredito.db"]["sha256"]
    )
    assert (root / ".atualizacoes" / "prebuilt-installed.json").is_file()
    with closing(sqlite3.connect(root / "car_microcredito.db")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sicor_mutuario").fetchone() == (
            1,
        )


def test_copy_install_rolls_back_renames_when_a_file_is_locked(
    prebuilt: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
    )

    root = tmp_path / "bases"
    PrebuiltReleaseBundle(prebuilt, TEST_PUBLIC_KEY_PEM).extract_data(root)
    history = root / ".h" / "history.txt"
    history.parent.mkdir()
    history.write_bytes(b"old history")
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    original_rename = Path.rename

    def locked_rename(path: Path, target: Path) -> Path:
        if path.parent.name == "new" and path.name == "ambientais":
            raise PermissionError("fixture: file open in another application")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", locked_rename)
    with pytest.raises(ValueError, match="estado anterior foi preservado"):
        _apply(prebuilt, root)

    assert all(
        (root / relative).read_bytes() == content
        for relative, content in before.items()
    )
    assert not (root / ".atualizacoes" / "external-update-pending.json").exists()
    assert not (root / ".atualizacoes" / "prebuilt-installed.json").exists()


def test_copy_install_does_not_replace_bases_during_a_consultation(
    prebuilt: Path, tmp_path: Path
) -> None:
    from qgis_plugin_microcredito.infrastructure.base_access import read_base_access
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
    )

    root = tmp_path / "bases"
    PrebuiltReleaseBundle(prebuilt, TEST_PUBLIC_KEY_PEM).extract_data(root)
    before = (root / "car_microcredito.db").read_bytes()
    with read_base_access(root), pytest.raises(ValueError, match="em andamento"):
        _apply(prebuilt, root)

    assert (root / "car_microcredito.db").read_bytes() == before
    assert not (root / ".atualizacoes" / "external-update-pending.json").exists()


def test_copy_install_removes_old_database_sidecars_before_activation(
    prebuilt: Path, tmp_path: Path
) -> None:
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
    )

    root = tmp_path / "bases"
    PrebuiltReleaseBundle(prebuilt, TEST_PUBLIC_KEY_PEM).extract_data(root)
    for suffix in ("-wal", "-shm", "-journal"):
        (root / ("car_microcredito.db" + suffix)).write_bytes(b"obsolete sidecar")

    _apply(prebuilt, root)

    assert not any(
        (root / ("car_microcredito.db" + suffix)).exists()
        for suffix in ("-wal", "-shm", "-journal")
    )
    with closing(sqlite3.connect(root / "car_microcredito.db")) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)


def test_older_snapshot_is_blocked_even_with_same_source_versions(
    prebuilt: Path, tmp_path: Path
) -> None:
    from qgis_plugin_microcredito.infrastructure.prebuilt_install import (
        compare_prebuilt_release,
    )
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
    )

    with zipfile.ZipFile(prebuilt) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["prebuilt.json"])
    issued = datetime.fromisoformat(manifest["issued_at"])
    packages = []
    for minutes in (2, 1):
        path = tmp_path / f"snapshot-{minutes}.carbases"
        manifest["issued_at"] = (issued - timedelta(minutes=minutes)).isoformat()
        with zipfile.ZipFile(path, "w") as archive:
            for name, payload in entries.items():
                archive.writestr(
                    name,
                    json.dumps(manifest).encode()
                    if name == "prebuilt.json"
                    else payload,
                )
        packages.append(path)
    older, newer = packages
    root = tmp_path / "bases"
    _apply(newer, root)
    installed_before = (root / ".atualizacoes" / "prebuilt-installed.json").read_bytes()

    statuses = compare_prebuilt_release(
        PrebuiltReleaseBundle(older, TEST_PUBLIC_KEY_PEM),
        root,
        root / "car_microcredito.db",
    )

    assert all(status.state == "inaplicavel" for status in statuses)
    with pytest.raises(ValueError, match="anterior"):
        _apply(older, root)
    assert (
        root / ".atualizacoes" / "prebuilt-installed.json"
    ).read_bytes() == installed_before


@pytest.mark.parametrize(
    "missing", ["car_microcredito.db", "car/RR/RR_AREA_IMOVEL.gpkg"]
)
def test_same_snapshot_repairs_a_missing_local_data_file(
    prebuilt: Path, tmp_path: Path, missing: str
) -> None:
    from qgis_plugin_microcredito.infrastructure.prebuilt_install import (
        compare_prebuilt_release,
    )
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
    )

    root = tmp_path / "bases"
    _apply(prebuilt, root)
    (root / missing).unlink()
    release = PrebuiltReleaseBundle(prebuilt, TEST_PUBLIC_KEY_PEM)
    statuses = compare_prebuilt_release(release, root, root / "car_microcredito.db")

    assert any(status.state == "disponivel" for status in statuses)
    _apply(prebuilt, root)
    assert (root / missing).is_file()
