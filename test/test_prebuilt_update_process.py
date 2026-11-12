"""Prepared data releases cross the same worker boundary as the QGIS plugin."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sysconfig
import zipfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest

from database.session import connect
from installer.plugin_build import build as build_plugin
from installer.prebuilt_bases import prepare_prebuilt_bases
from prebuilt_support import SYNTHETIC_CAR, write_complete_release
from qgis_plugin_microcredito.application.query_service import (
    find_by_car,
    find_mma_mcr_by_car,
    find_operation_context,
    find_slave_labor_by_documents,
)
from qgis_plugin_microcredito.infrastructure.base_access import EXTERNAL_UPDATE_PENDING
from update_process_support import TEST_PUBLIC_KEY_PEM

ROOT = Path(__file__).parents[1]
WORKER = ROOT / "src" / "plugin" / "update_worker.py"


@dataclass(frozen=True)
class PreparedRelease:
    candidate: Path
    release: Path
    public_key: Path


@pytest.fixture
def prepared_release(tmp_path: Path) -> PreparedRelease:
    from installer.prebuilt_release import build_prebuilt_release

    source = write_complete_release(tmp_path / "source")
    candidate = tmp_path / "candidate"
    manifest_path = prepare_prebuilt_bases(
        source.release, candidate, TEST_PUBLIC_KEY_PEM
    )
    manifest = json.loads(manifest_path.read_bytes())
    manifest["prepared_at"] = "2026-10-27T10:00:00-03:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    release = tmp_path / "bases-plugin-27-10-2026.carbases"
    build_prebuilt_release(candidate, release, TEST_PUBLIC_KEY_PEM)
    return PreparedRelease(candidate, release, source.public_key)


def _request(release: PreparedRelease, data_root: Path) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "command": "validate",
        "release_path": str(release.release),
        "data_root": str(data_root),
        "database": str(data_root / "car_microcredito.db"),
    }


def _run_worker(
    request: dict[str, object],
    public_key: Path,
    *,
    worker: Path = WORKER,
    cwd: Path = ROOT,
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    # Skip editable-install .pth files as well as PYTHONPATH. Only the worker's
    # own bootstrap may select the application code; regular deps remain usable.
    runtime = Path(sys.base_prefix).resolve()
    dll_directories = (
        [path for path in (runtime, runtime / "DLLs") if path.is_dir()]
        if sys.platform == "win32"
        else []
    )
    configured_root = environment.get("OSGEO4W_ROOT")
    if sys.platform == "win32" and configured_root:
        native_root = Path(configured_root).resolve()
        native_bin = native_root / "bin"
        if runtime.is_relative_to(native_root) and native_bin.is_dir():
            dll_directories.append(native_bin)
    bootstrap = (
        "import json, os, runpy, sys; "
        "dll_handles = [os.add_dll_directory(p) for p in json.loads(sys.argv[2])]; "
        "sys.path.extend(json.loads(sys.argv[1])); "
        "sys.argv = sys.argv[3:]; "
        "runpy.run_path(sys.argv[0], run_name='__main__')"
    )
    dependencies = sorted(
        {sysconfig.get_path("purelib"), sysconfig.get_path("platlib")}
    )
    return subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-I",
            "-S",
            "-u",
            "-c",
            bootstrap,
            json.dumps(dependencies),
            json.dumps([str(path) for path in dll_directories]),
            str(worker),
            "--public-key-file",
            str(public_key),
        ],
        input=json.dumps(request),
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=cwd,
        env=environment,
        check=False,
        timeout=40,
    )


def _events(process: subprocess.CompletedProcess[str]) -> list[dict[str, object]]:
    events = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    return [event for event in events if event.get("event") != "heartbeat"]


def _result(process: subprocess.CompletedProcess[str]) -> object:
    assert process.returncode == 0, (process.stdout, process.stderr)
    events = _events(process)
    assert events[-1]["event"] == "result", events
    return events[-1]["payload"]


def _assert_queryable_bases(data_root: Path) -> None:
    with closing(
        connect(data_root / "car_microcredito.db", readonly=True)
    ) as connection:
        properties = find_by_car(connection, SYNTHETIC_CAR)
        assert len(properties) == 1
        assert properties[0]["ref_bacen"] == "1"
        assert len(find_mma_mcr_by_car(connection, SYNTHETIC_CAR)) == 1
        assert len(find_slave_labor_by_documents(connection, ["00000000000"])) == 1
        operation = find_operation_context(connection, "1", "1")
        assert operation["total_glebas"] == 1
    assert len(list((data_root / "car").rglob("*.gpkg"))) == 27
    assert len(list((data_root / "ambientais").glob("*.gpkg"))) == 6
    assert not (data_root / ".atualizacoes" / EXTERNAL_UPDATE_PENDING).exists()


def test_validate_prebuilt_release_reports_integrity_without_creating_user_bases(
    prepared_release: PreparedRelease, tmp_path: Path
) -> None:
    data_root = tmp_path / "user-bases"

    process = _run_worker(
        _request(prepared_release, data_root), prepared_release.public_key
    )

    events = _events(process)
    assert process.returncode == 0, (process.stdout, process.stderr)
    assert events[0]["event"] == "started"
    assert events[-1]["event"] == "result"
    payload = events[-1]["payload"]
    assert isinstance(payload, dict)
    assert payload["release_format"] == "prebuilt"
    assert len(payload["catalog"]["packages"]) == 36
    assert {entry["state"] for entry in payload["statuses"]} == {"disponivel"}
    assert len(payload["catalog_fingerprint"]) == 64
    assert not data_root.exists()


def test_prebuilt_apply_in_worker_installs_queryable_bases_and_repeat_is_current(
    prepared_release: PreparedRelease, tmp_path: Path
) -> None:
    data_root = tmp_path / "user-bases"
    request = _request(prepared_release, data_root)
    validated = _result(_run_worker(request, prepared_release.public_key))
    assert isinstance(validated, dict)

    process = _run_worker(
        {
            **request,
            "command": "apply",
            "expected_catalog_fingerprint": validated["catalog_fingerprint"],
        },
        prepared_release.public_key,
    )

    installed = _result(process)
    assert isinstance(installed, list)
    assert len(installed) == 36
    assert {entry["state"] for entry in installed} == {"atual"}
    _assert_queryable_bases(data_root)
    repeated = _result(_run_worker(request, prepared_release.public_key))
    assert isinstance(repeated, dict)
    assert {entry["state"] for entry in repeated["statuses"]} == {"atual"}


def test_republished_snapshot_with_same_catalog_requires_validation_and_application(
    prepared_release: PreparedRelease, tmp_path: Path
) -> None:
    from installer.prebuilt_release import build_prebuilt_release

    data_root = tmp_path / "user-bases"
    request = _request(prepared_release, data_root)
    first = _result(_run_worker(request, prepared_release.public_key))
    assert isinstance(first, dict)
    _result(
        _run_worker(
            {
                **request,
                "command": "apply",
                "expected_catalog_fingerprint": first["catalog_fingerprint"],
            },
            prepared_release.public_key,
        )
    )
    manifest_path = prepared_release.candidate / "snapshot.candidate.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["prepared_at"] = "2026-10-27T11:00:00-03:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    updated = tmp_path / "reissued" / prepared_release.release.name
    build_prebuilt_release(prepared_release.candidate, updated, TEST_PUBLIC_KEY_PEM)
    prepared_release.release.write_bytes(updated.read_bytes())

    second = _result(_run_worker(request, prepared_release.public_key))
    assert isinstance(second, dict)
    assert first["catalog"] == second["catalog"]
    assert first["catalog_fingerprint"] != second["catalog_fingerprint"]
    assert {entry["state"] for entry in second["statuses"]} == {"disponivel"}
    rejected = _run_worker(
        {
            **request,
            "command": "apply",
            "expected_catalog_fingerprint": first["catalog_fingerprint"],
        },
        prepared_release.public_key,
    )
    assert rejected.returncode != 0
    assert "mudou desde a validação" in str(_events(rejected)[-1]["message"])
    _assert_queryable_bases(data_root)
    updated_installation = _result(
        _run_worker(
            {
                **request,
                "command": "apply",
                "expected_catalog_fingerprint": second["catalog_fingerprint"],
            },
            prepared_release.public_key,
        )
    )
    assert isinstance(updated_installation, list)
    assert {entry["state"] for entry in updated_installation} == {"atual"}
    _assert_queryable_bases(data_root)
    repeated = _result(_run_worker(request, prepared_release.public_key))
    assert isinstance(repeated, dict)
    assert {entry["state"] for entry in repeated["statuses"]} == {"atual"}


def test_distributable_plugin_worker_copies_bases_without_checkout_code(
    prepared_release: PreparedRelease, tmp_path: Path
) -> None:
    archive_path = build_plugin(destination=tmp_path / "plugin.zip")
    plugin_directory = tmp_path / "extracted-plugin"
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(plugin_directory)
    worker = plugin_directory / "car_microcredito_qgis" / "update_worker.py"
    assert worker.is_file()
    assert not (worker.parent / "lib" / "installer").exists()
    outside_checkout = tmp_path / "outside-checkout"
    outside_checkout.mkdir()
    data_root = tmp_path / "user-bases"
    request = _request(prepared_release, data_root)

    validated = _result(
        _run_worker(
            request,
            prepared_release.public_key,
            worker=worker,
            cwd=outside_checkout,
        )
    )
    assert isinstance(validated, dict)
    assert validated["release_format"] == "prebuilt"
    applied = _result(
        _run_worker(
            {
                **request,
                "command": "apply",
                "expected_catalog_fingerprint": validated["catalog_fingerprint"],
            },
            prepared_release.public_key,
            worker=worker,
            cwd=outside_checkout,
        )
    )
    assert isinstance(applied, list)
    assert {entry["state"] for entry in applied} == {"atual"}
    _assert_queryable_bases(data_root)
