from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from prebuilt_support import write_complete_release
from update_process_support import TEST_PUBLIC_KEY_PEM


@pytest.fixture
def candidate(tmp_path: Path) -> Path:
    from installer.prebuilt_bases import prepare_prebuilt_bases

    source = write_complete_release(tmp_path / "source")
    destination = tmp_path / "candidate"
    prepare_prebuilt_bases(source.release, destination, TEST_PUBLIC_KEY_PEM)
    return destination


def test_prebuilt_bundle_round_trip_copies_all_data_and_binds_manifest(
    candidate: Path,
    tmp_path: Path,
) -> None:
    from installer.prebuilt_release import build_prebuilt_release
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
        is_prebuilt_release,
    )

    manifest = json.loads((candidate / "snapshot.candidate.json").read_bytes())
    manifest["prepared_at"] = "2026-10-27T23:59:00-03:00"
    (candidate / "snapshot.candidate.json").write_text(json.dumps(manifest))
    output = tmp_path / "bases-plugin-27-10-2026.carbases"
    result = build_prebuilt_release(candidate, output, TEST_PUBLIC_KEY_PEM)

    assert result["files"] == 35
    assert is_prebuilt_release(output)
    bundle = PrebuiltReleaseBundle(output, TEST_PUBLIC_KEY_PEM)
    assert len(bundle.fetch_catalog().packages) == 36
    assert len(bundle.manifest["components"]) == 37
    assert len(bundle.fingerprint) == 64
    copied = tmp_path / "copied"
    bundle.extract_data(copied)
    assert len([path for path in copied.rglob("*") if path.is_file()]) == 35
    for relative, descriptor in manifest["files"].items():
        path = copied / relative
        assert path.stat().st_size == descriptor["size_bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == descriptor["sha256"]
    with zipfile.ZipFile(output) as archive:
        assert "prebuilt.json" in archive.namelist()
        assert "catalog.json" not in archive.namelist()
        assert not any(name.startswith("packages/") for name in archive.namelist())


def _build(candidate: Path, destination: Path) -> Path:
    from installer.prebuilt_release import build_prebuilt_release

    manifest = json.loads((candidate / "snapshot.candidate.json").read_bytes())
    date = manifest["prepared_at"][:10]
    year, month, day = date.split("-")
    destination.mkdir()
    path = destination / f"bases-plugin-{day}-{month}-{year}.carbases"
    build_prebuilt_release(candidate, path, TEST_PUBLIC_KEY_PEM)
    return path


def _rewrite(
    path: Path, changes: dict[str, bytes], *, remove: str | None = None
) -> None:
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    if remove is not None:
        del entries[remove]
    entries.update(changes)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


@pytest.mark.parametrize(
    "fault",
    [
        "corrupt",
        "corrupt_same_size",
        "missing",
        "extra",
        "duplicate",
        "traversal",
        "schema",
    ],
)
def test_prebuilt_reader_rejects_invalid_bundle_without_extracting(
    candidate: Path,
    tmp_path: Path,
    fault: str,
) -> None:
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
    )

    path = _build(candidate, tmp_path / "release")
    if fault == "corrupt":
        _rewrite(path, {"data/car_microcredito.db": b"corrupted database"})
    elif fault == "corrupt_same_size":
        with zipfile.ZipFile(path) as archive:
            original = archive.read("data/car_microcredito.db")
        _rewrite(
            path, {"data/car_microcredito.db": bytes([original[0] ^ 1]) + original[1:]}
        )
    elif fault == "missing":
        _rewrite(path, {}, remove="data/car/AC/AC_AREA_IMOVEL.gpkg")
    elif fault == "extra":
        _rewrite(path, {"extra.txt": b"unexpected"})
    elif fault == "traversal":
        _rewrite(path, {"data/../outside.txt": b"unexpected"})
    elif fault == "schema":
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("prebuilt.json"))
        manifest["database_schema_version"] = 999
        _rewrite(path, {"prebuilt.json": json.dumps(manifest).encode()})
    else:
        with zipfile.ZipFile(path, "a") as archive:
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("prebuilt.json", b"{}")

    with pytest.raises(ValueError):
        PrebuiltReleaseBundle(path, TEST_PUBLIC_KEY_PEM)
    assert not (tmp_path / "outside.txt").exists()


def test_builder_rejects_changed_candidate_and_preserves_existing_output(
    candidate: Path,
    tmp_path: Path,
) -> None:
    from installer.prebuilt_release import build_prebuilt_release

    destination = tmp_path / "bases-plugin-28-10-2026.carbases"
    destination.write_bytes(b"previous release")
    with pytest.raises(ValueError, match="destino deve ser novo"):
        build_prebuilt_release(candidate, destination, TEST_PUBLIC_KEY_PEM)
    assert destination.read_bytes() == b"previous release"
    (candidate / "ambientais" / "embargos.gpkg").write_bytes(
        b"changed after preparation"
    )
    destination.unlink()
    with pytest.raises(ValueError):
        _build(candidate, tmp_path / "invalid")
    assert not list((tmp_path / "invalid").glob("*.carbases"))
    assert not list((tmp_path / "invalid").glob("*.part"))


def test_extraction_revalidates_data_and_fingerprint_after_validation(
    candidate: Path,
    tmp_path: Path,
) -> None:
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
    )

    path = _build(candidate, tmp_path / "release")
    first = PrebuiltReleaseBundle(path, TEST_PUBLIC_KEY_PEM)
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("prebuilt.json"))
    manifest["release_note"] = "second snapshot with identical source catalog"
    _rewrite(path, {"prebuilt.json": json.dumps(manifest).encode()})
    second = PrebuiltReleaseBundle(path, TEST_PUBLIC_KEY_PEM)
    assert first.fetch_catalog() == second.fetch_catalog()
    assert first.fingerprint != second.fingerprint
    destination = tmp_path / "copied"
    with pytest.raises(ValueError, match="mudou desde a validação"):
        first.extract_data(destination)
    assert not destination.exists()


def test_extraction_rejects_existing_destination_without_altering_it(
    candidate: Path,
    tmp_path: Path,
) -> None:
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
    )

    path = _build(candidate, tmp_path / "release")
    bundle = PrebuiltReleaseBundle(path, TEST_PUBLIC_KEY_PEM)
    destination = tmp_path / "installed"
    destination.mkdir()
    sentinel = destination / "car_microcredito.db"
    sentinel.write_bytes(b"operational")
    with pytest.raises(ValueError, match="destino da cópia deve ser novo"):
        bundle.extract_data(destination)
    assert sentinel.read_bytes() == b"operational"


def test_extraction_checks_hashes_again_and_cleans_failed_copy(
    candidate: Path,
    tmp_path: Path,
) -> None:
    from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
        PrebuiltReleaseBundle,
    )

    path = _build(candidate, tmp_path / "release")
    bundle = PrebuiltReleaseBundle(path, TEST_PUBLIC_KEY_PEM)
    with zipfile.ZipFile(path) as archive:
        original = archive.read("data/car_microcredito.db")
    _rewrite(
        path, {"data/car_microcredito.db": bytes([original[0] ^ 1]) + original[1:]}
    )
    destination = tmp_path / "copied"
    with pytest.raises(ValueError, match="Integridade divergente"):
        bundle.extract_data(destination)
    assert not destination.exists()
